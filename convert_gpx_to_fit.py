import math
import random
import datetime
import gpxpy
from garmin_fit_sdk import Encoder, Stream, Decoder

def haversine_distance(lat1, lon1, lat2, lon2):
    R = 6371000.0  # Earth radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (math.sin(delta_phi / 2.0) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2)
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c

def deg_to_semicircles(deg):
    return int(deg * (2**31 / 180.0))

def generate_natural_fit(gpx_path, output_fit_path, start_time_utc=None, avg_pace_min_km=8.33):
    # avg_pace_min_km = 8.33 -> ~8:20/km -> ~7.2 km/h -> 2.0 m/s
    with open(gpx_path, 'r', encoding='utf-8') as f:
        gpx = gpxpy.parse(f)

    raw_points = []
    for trk in gpx.tracks:
        for seg in trk.segments:
            for pt in seg.points:
                raw_points.append(pt)

    if not raw_points:
        for rte in gpx.routes:
            for pt in rte.points:
                raw_points.append(pt)

    if not raw_points:
        raise ValueError("No points found in GPX file")

    print(f"Loaded {len(raw_points)} points from GPX.")

    # Calculate cumulative distance along raw GPX track
    cum_dist = [0.0]
    total_dist = 0.0
    elevations = [raw_points[0].elevation or 5.0]

    for i in range(1, len(raw_points)):
        d = haversine_distance(raw_points[i-1].latitude, raw_points[i-1].longitude,
                               raw_points[i].latitude, raw_points[i].longitude)
        total_dist += d
        cum_dist.append(total_dist)
        elevations.append(raw_points[i].elevation if raw_points[i].elevation is not None else elevations[-1])

    print(f"Total distance: {total_dist:.2f} m ({total_dist/1000:.2f} km)")

    # Target speed: avg_pace_min_km in minutes per km
    # pace in min/km -> speed in m/s: 1000 m / (pace * 60 s)
    target_avg_speed = 1000.0 / (avg_pace_min_km * 60.0) # ~2.0 m/s (7.2 km/h)
    estimated_total_seconds = int(total_dist / target_avg_speed)
    print(f"Estimated duration: {estimated_total_seconds // 60}m {estimated_total_seconds % 60}s at avg speed {target_avg_speed*3.6:.2f} km/h")

    # Generate smooth natural speed profile
    random.seed(42)
    speeds = []
    current_speed = target_avg_speed * 0.8  # start a bit slower (warm-up)
    
    for t in range(estimated_total_seconds):
        # Progress from 0 to 1
        progress = t / estimated_total_seconds
        
        # Warmup for first 2 mins, cooldown for last 1 min
        if progress < 0.05:
            target_t = target_avg_speed * (0.8 + 0.2 * (progress / 0.05))
        elif progress > 0.95:
            target_t = target_avg_speed * (1.0 - 0.15 * ((progress - 0.95) / 0.05))
        else:
            target_t = target_avg_speed
        
        # Gentle random fluctuation with momentum
        noise = (random.random() - 0.5) * 0.06
        current_speed = 0.96 * current_speed + 0.04 * target_t + noise
        # Bound between 1.6 m/s (5.76 km/h) and 2.3 m/s (8.28 km/h)
        current_speed = max(1.6, min(2.35, current_speed))
        speeds.append(current_speed)

    # Adjust speeds slightly so sum(speeds) == total_dist
    dist_sum = sum(speeds)
    scale_factor = total_dist / dist_sum
    speeds = [s * scale_factor for s in speeds]

    # Calculate timestamps and cumulative distance per second
    if start_time_utc is None:
        # Start time: 3:22 PM (15:22:00) Vietnam time (UTC+7) -> 08:22:00 UTC
        start_time_utc = datetime.datetime(2026, 9, 25, 8, 22, 0, tzinfo=datetime.timezone.utc)

    # Build second-by-second records
    records = []
    cur_d = 0.0
    seg_idx = 0
    num_pts = len(raw_points)

    total_ascent = 0.0
    total_descent = 0.0
    last_ele = elevations[0]

    for t, s in enumerate(speeds):
        rec_time = start_time_utc + datetime.timedelta(seconds=t)
        cur_d += s
        if cur_d > total_dist:
            cur_d = total_dist

        # Find segment in GPX
        while seg_idx < num_pts - 1 and cum_dist[seg_idx + 1] < cur_d:
            seg_idx += 1

        if seg_idx >= num_pts - 1:
            lat = raw_points[-1].latitude
            lon = raw_points[-1].longitude
            ele = elevations[-1]
        else:
            p0 = raw_points[seg_idx]
            p1 = raw_points[seg_idx + 1]
            d0 = cum_dist[seg_idx]
            d1 = cum_dist[seg_idx + 1]
            seg_len = d1 - d0
            ratio = (cur_d - d0) / seg_len if seg_len > 0 else 0.0
            ratio = max(0.0, min(1.0, ratio))

            lat = p0.latitude + ratio * (p1.latitude - p0.latitude)
            lon = p0.longitude + ratio * (p1.longitude - p0.longitude)
            ele = elevations[seg_idx] + ratio * (elevations[seg_idx + 1] - elevations[seg_idx])

        # Realistic cadence for brisk walking / slow jog: 132 - 146 spm
        # Slightly correlated with speed
        base_cadence = 120 + (s / target_avg_speed) * 18
        cadence_spm = int(base_cadence + random.randint(-1, 1))
        # Garmin FIT format stores running cadence in strides/min (half of SPM).
        fit_cad = max(30, min(110, int(round(cadence_spm / 2.0))))

        # Realistic heart rate:
        # starts ~98 bpm, climbs to 118-128 bpm, fluctuates naturally
        warmup_factor = min(1.0, t / 300.0) # 5 min warmup
        target_hr = 95 + warmup_factor * 26 + (s - target_avg_speed) * 8
        hr = int(target_hr + random.randint(-1, 1))

        records.append({
            'timestamp': rec_time,
            'position_lat': deg_to_semicircles(lat),
            'position_long': deg_to_semicircles(lon),
            'distance': round(cur_d, 2),
            'speed': round(s, 3),
            'enhanced_speed': round(s, 3),
            'altitude': round(ele, 2),
            'enhanced_altitude': round(ele, 2),
            'cadence': fit_cad,
            'heart_rate': hr,
            '_spm': cadence_spm
        })

    end_time_utc = records[-1]['timestamp']
    total_elapsed = (end_time_utc - start_time_utc).total_seconds()
    avg_speed = total_dist / total_elapsed
    max_speed = max(r['speed'] for r in records)

    avg_spm = int(sum(r['_spm'] for r in records) / len(records))
    max_spm = max(r['_spm'] for r in records)
    avg_cad_fit = int(round(avg_spm / 2.0))
    max_cad_fit = int(round(max_spm / 2.0))

    avg_hr = int(sum(r['heart_rate'] for r in records) / len(records))
    max_hr = max(r['heart_rate'] for r in records)

    # Calculate realistic elevation ascent/descent with 0.5m hysteresis
    total_ascent = 0.0
    total_descent = 0.0
    last_h = elevations[0]
    for e in elevations[1:]:
        diff = e - last_h
        if abs(diff) >= 0.5:
            if diff > 0:
                total_ascent += diff
            else:
                total_descent += abs(diff)
            last_h = e
    total_ascent = max(1.0, round(total_ascent, 1))
    total_descent = max(1.0, round(total_descent, 1))

    print(f"Generated {len(records)} records.")
    print(f"Start: {start_time_utc} | End: {end_time_utc}")
    print(f"Elapsed: {total_elapsed:.0f}s ({total_elapsed/60:.1f} mins)")
    print(f"Avg Speed: {avg_speed*3.6:.2f} km/h (Pace: {60/(avg_speed*3.6):.2f} min/km) | Max Speed: {max_speed*3.6:.2f} km/h")
    print(f"Human Steps (SPM): Avg {avg_spm} spm, Max {max_spm} spm -> FIT Cadence: Avg {avg_cad_fit} rpm, Max {max_cad_fit} rpm")
    print(f"Avg HR: {avg_hr} bpm | Max HR: {max_hr} bpm")
    print(f"Total Ascent: {total_ascent:.1f}m | Total Descent: {total_descent:.1f}m")

    # Encode FIT file
    encoder = Encoder()

    # 1. file_id
    encoder.write_mesg({
        'mesg_num': 0, # file_id
        'type': 'activity',
        'manufacturer': 'strava',
        'product': 101,
        'time_created': start_time_utc,
    })

    # 2. device_info
    encoder.write_mesg({
        'mesg_num': 23, # device_info
        'device_index': 0,
        'manufacturer': 'strava',
        'product': 101,
        'timestamp': start_time_utc,
    })

    # 3. event timer start
    encoder.write_mesg({
        'mesg_num': 21, # event
        'event': 'timer',
        'event_type': 'start',
        'timer_trigger': 'manual',
        'timestamp': start_time_utc,
    })

    # 4. records
    for rec in records:
        encoder.write_mesg({
            'mesg_num': 20, # record
            **rec
        })

    # 5. event timer stop
    encoder.write_mesg({
        'mesg_num': 21, # event
        'event': 'timer',
        'event_type': 'stop',
        'timer_trigger': 'manual',
        'timestamp': end_time_utc,
    })

    # 6. lap
    encoder.write_mesg({
        'mesg_num': 19, # lap
        'event': 'lap',
        'event_type': 'stop',
        'lap_trigger': 'session_end',
        'sport': 'running',
        'sub_sport': 'generic',
        'start_time': start_time_utc,
        'timestamp': end_time_utc,
        'total_elapsed_time': round(total_elapsed, 3),
        'total_timer_time': round(total_elapsed, 3),
        'total_distance': round(total_dist, 2),
        'avg_speed': round(avg_speed, 3),
        'max_speed': round(max_speed, 3),
        'avg_cadence': avg_cad_fit,
        'max_cadence': max_cad_fit,
        'avg_heart_rate': avg_hr,
        'max_heart_rate': max_hr,
        'total_ascent': round(total_ascent, 1),
        'total_descent': round(total_descent, 1),
    })

    # 7. session
    encoder.write_mesg({
        'mesg_num': 18, # session
        'event': 'session',
        'event_type': 'stop',
        'sport': 'running',
        'sub_sport': 'generic',
        'start_time': start_time_utc,
        'timestamp': end_time_utc,
        'total_elapsed_time': round(total_elapsed, 3),
        'total_timer_time': round(total_elapsed, 3),
        'total_distance': round(total_dist, 2),
        'avg_speed': round(avg_speed, 3),
        'max_speed': round(max_speed, 3),
        'avg_cadence': avg_cad_fit,
        'max_cadence': max_cad_fit,
        'avg_heart_rate': avg_hr,
        'max_heart_rate': max_hr,
        'total_ascent': round(total_ascent, 1),
        'total_descent': round(total_descent, 1),
        'first_lap_index': 0,
        'num_laps': 1,
    })

    # 8. activity
    FIT_EPOCH_S = 631065600
    local_ts_int = int(end_time_utc.timestamp()) - FIT_EPOCH_S + 7 * 3600
    encoder.write_mesg({
        'mesg_num': 34, # activity
        'event': 'activity',
        'event_type': 'stop',
        'timestamp': end_time_utc,
        'local_timestamp': local_ts_int,
        'num_sessions': 1,
        'total_timer_time': round(total_elapsed, 3),
        'type': 'manual',
    })

    # Finalize
    fit_bytes = encoder.close()
    with open(output_fit_path, 'wb') as f:
        f.write(fit_bytes)

    print(f"Successfully generated FIT file: {output_fit_path} ({len(fit_bytes)} bytes)")
    return output_fit_path

if __name__ == '__main__':
    generate_natural_fit('New file 1.gpx', 'activity_walk_run_modified.fit')
