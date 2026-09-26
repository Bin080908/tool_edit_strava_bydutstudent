import os
import math
import random
import datetime
import webbrowser
from threading import Timer
from flask import Flask, render_template, request, jsonify, send_file
import gpxpy
from garmin_fit_sdk import Encoder, util

app = Flask(__name__)

@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
    response.headers['Access-Control-Allow-Methods'] = 'GET,PUT,POST,DELETE,OPTIONS'
    return response

@app.before_request
def handle_preflight():
    if request.method == "OPTIONS":
        res = app.make_default_options_response()
        res.headers['Access-Control-Allow-Origin'] = '*'
        res.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
        res.headers['Access-Control-Allow-Methods'] = 'GET,PUT,POST,DELETE,OPTIONS'
        return res

WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(WORKSPACE_DIR, 'uploads')
OUTPUT_DIR = os.path.join(WORKSPACE_DIR, 'outputs')
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

def haversine_distance(lat1, lon1, lat2, lon2):
    R = 6371000.0
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

def parse_gpx_points(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        gpx = gpxpy.parse(f)

    points = []
    for trk in gpx.tracks:
        for seg in trk.segments:
            for pt in seg.points:
                points.append({
                    'lat': pt.latitude,
                    'lon': pt.longitude,
                    'ele': pt.elevation if pt.elevation is not None else 5.0
                })
    if not points:
        for rte in gpx.routes:
            for pt in rte.points:
                points.append({
                    'lat': pt.latitude,
                    'lon': pt.longitude,
                    'ele': pt.elevation if pt.elevation is not None else 5.0
                })

    if not points:
        raise ValueError("File GPX không chứa toạ độ (trackpoints/route points).")

    # Calculate cumulative distance
    cum_dist = [0.0]
    total_dist = 0.0
    for i in range(1, len(points)):
        d = haversine_distance(points[i-1]['lat'], points[i-1]['lon'],
                               points[i]['lat'], points[i]['lon'])
        total_dist += d
        cum_dist.append(total_dist)

    for i, pt in enumerate(points):
        pt['dist'] = cum_dist[i]

    return points, total_dist

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/list_files', methods=['GET'])
def list_files():
    # Scan workspace for .gpx files
    files = []
    for f in os.listdir(WORKSPACE_DIR):
        if f.lower().endswith('.gpx'):
            files.append({'name': f, 'path': os.path.join(WORKSPACE_DIR, f)})
    for f in os.listdir(UPLOAD_DIR):
        if f.lower().endswith('.gpx'):
            files.append({'name': f"uploads/{f}", 'path': os.path.join(UPLOAD_DIR, f)})
    return jsonify({'files': files})

@app.route('/api/parse_gpx', methods=['POST'])
def api_parse_gpx():
    try:
        data = request.json or {}
        filepath = data.get('filepath')
        if not filepath or not os.path.exists(filepath):
            return jsonify({'error': 'Không tìm thấy file'}), 400

        points, total_dist = parse_gpx_points(filepath)
        
        # Sample points for quick map display (max 500 pts to keep map fast)
        step = max(1, len(points) // 500)
        display_points = [[p['lat'], p['lon'], round(p['ele'], 1)] for p in points[::step]]
        if display_points[-1] != [points[-1]['lat'], points[-1]['lon'], round(points[-1]['ele'], 1)]:
            display_points.append([points[-1]['lat'], points[-1]['lon'], round(points[-1]['ele'], 1)])

        return jsonify({
            'success': True,
            'total_distance_m': round(total_dist, 2),
            'total_distance_km': round(total_dist / 1000.0, 2),
            'num_points': len(points),
            'start_coords': [points[0]['lat'], points[0]['lon']],
            'end_coords': [points[-1]['lat'], points[-1]['lon']],
            'display_points': display_points,
            'filepath': filepath
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/upload_gpx', methods=['POST'])
def api_upload_gpx():
    if 'file' not in request.files:
        return jsonify({'error': 'Không có file gửi kèm'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'Tên file rỗng'}), 400

    filename = file.filename
    save_path = os.path.join(UPLOAD_DIR, filename)
    file.save(save_path)

    try:
        points, total_dist = parse_gpx_points(save_path)
        step = max(1, len(points) // 500)
        display_points = [[p['lat'], p['lon'], round(p['ele'], 1)] for p in points[::step]]
        if display_points[-1] != [points[-1]['lat'], points[-1]['lon'], round(points[-1]['ele'], 1)]:
            display_points.append([points[-1]['lat'], points[-1]['lon'], round(points[-1]['ele'], 1)])

        return jsonify({
            'success': True,
            'filename': filename,
            'filepath': save_path,
            'total_distance_m': round(total_dist, 2),
            'total_distance_km': round(total_dist / 1000.0, 2),
            'num_points': len(points),
            'start_coords': [points[0]['lat'], points[0]['lon']],
            'end_coords': [points[-1]['lat'], points[-1]['lon']],
            'display_points': display_points
        })
    except Exception as e:
        return jsonify({'error': f'Lỗi đọc GPX: {str(e)}'}), 400

@app.route('/api/generate_fit', methods=['POST'])
def api_generate_fit():
    try:
        data = request.json or {}
        filepath = data.get('filepath')
        if not filepath or not os.path.exists(filepath):
            return jsonify({'error': 'Đường dẫn file không hợp lệ'}), 400

        # Parameters
        activity_type = data.get('activity_type', 'Run') # Run, Walk, Ride
        sport = 'running' if activity_type in ['Run', 'Walk'] else 'cycling'
        sub_sport = 'generic'
        
        # Pace / Speed
        # avg_pace_min_km (e.g. 8.33 min/km)
        avg_pace_min = float(data.get('avg_pace_min', 8.33)) # in minutes
        target_avg_speed = 1000.0 / (avg_pace_min * 60.0) # in m/s

        # Start Time: ISO string e.g. "2026-09-25T15:22:00"
        start_time_str = data.get('start_time')
        if start_time_str:
            local_start_dt = datetime.datetime.fromisoformat(start_time_str)
        else:
            local_start_dt = datetime.datetime.now()

        # Biometrics config
        base_cadence = int(data.get('cadence', 137 if sport == 'running' else 85))
        base_hr = int(data.get('heart_rate', 120))
        natural_variance = float(data.get('natural_variance', 0.8)) # 0.0 to 1.5

        # Output file name
        out_name = data.get('filename') or f"activity_{local_start_dt.strftime('%Y%m%d_%H%M%S')}.fit"
        if not out_name.endswith('.fit'):
            out_name += '.fit'
        output_path = os.path.join(WORKSPACE_DIR, out_name)

        # Parse GPX
        points, total_dist = parse_gpx_points(filepath)
        cum_dist = [p['dist'] for p in points]
        elevations = [p['ele'] for p in points]

        # Convert local_start_dt to UTC (assuming UTC+7 for Vietnam)
        # Or standard local to UTC conversion
        utc_offset_hours = float(data.get('utc_offset', 7.0))
        start_time_utc = local_start_dt.replace(tzinfo=datetime.timezone.utc) - datetime.timedelta(hours=utc_offset_hours)

        estimated_total_seconds = max(10, int(total_dist / target_avg_speed))

        # Realistic elevation ascent/descent with hysteresis threshold (0.5m)
        total_ascent = 0.0
        total_descent = 0.0
        last_ascent_mark = elevations[0]
        for e in elevations[1:]:
            diff = e - last_ascent_mark
            if abs(diff) >= 0.5:
                if diff > 0:
                    total_ascent += diff
                else:
                    total_descent += abs(diff)
                last_ascent_mark = e
        total_ascent = max(1.0, round(total_ascent, 1))
        total_descent = max(1.0, round(total_descent, 1))

        # Generate smooth natural speeds closely centered on target_avg_speed
        random.seed(int(start_time_utc.timestamp()))
        speeds = []
        cur_spd = target_avg_speed * 0.94

        for t in range(estimated_total_seconds):
            prog = t / float(estimated_total_seconds)
            # Warm-up (first 3%), Cool-down (last 3%), middle stays within +/- 4%
            if prog < 0.03:
                tgt = target_avg_speed * (0.92 + 0.08 * (prog / 0.03))
            elif prog > 0.97:
                tgt = target_avg_speed * (1.0 - 0.06 * ((prog - 0.97) / 0.03))
            else:
                osc = math.sin(prog * 24.0) * 0.03 * natural_variance
                tgt = target_avg_speed * (1.0 + osc)

            noise = (random.random() - 0.5) * 0.04 * natural_variance
            cur_spd = 0.95 * cur_spd + 0.05 * tgt + noise
            # Bound within realistic +/- 12% range of target speed
            cur_spd = max(target_avg_speed * 0.85, min(target_avg_speed * 1.15, cur_spd))
            speeds.append(cur_spd)

        scale_f = total_dist / sum(speeds)
        speeds = [s * scale_f for s in speeds]

        records = []
        cur_d = 0.0
        seg_idx = 0
        num_pts = len(points)
        raw_spms = []

        for t, s in enumerate(speeds):
            rec_time = start_time_utc + datetime.timedelta(seconds=t)
            cur_d += s
            if cur_d > total_dist:
                cur_d = total_dist

            while seg_idx < num_pts - 1 and cum_dist[seg_idx + 1] < cur_d:
                seg_idx += 1

            if seg_idx >= num_pts - 1:
                lat = points[-1]['lat']
                lon = points[-1]['lon']
                ele = elevations[-1]
            else:
                p0 = points[seg_idx]
                p1 = points[seg_idx + 1]
                d0 = cum_dist[seg_idx]
                d1 = cum_dist[seg_idx + 1]
                seg_len = d1 - d0
                ratio = (cur_d - d0) / seg_len if seg_len > 0 else 0.0
                ratio = max(0.0, min(1.0, ratio))

                lat = p0['lat'] + ratio * (p1['lat'] - p0['lat'])
                lon = p0['lon'] + ratio * (p1['lon'] - p0['lon'])
                ele = elevations[seg_idx] + ratio * (elevations[seg_idx + 1] - elevations[seg_idx])

            # Cadence: Human steps per minute (SPM)
            spm = int(base_cadence + (s - target_avg_speed) * 10 * natural_variance + random.randint(-1, 1))
            spm = max(60, min(210, spm))
            raw_spms.append(spm)

            # Garmin FIT protocol: for running, cadence is stored in strides/min (half of SPM)
            # Strava multiplies FIT cadence by 2 to display steps/min.
            if sport == 'running':
                fit_cad = max(30, min(110, int(round(spm / 2.0))))
            else:
                fit_cad = max(30, min(150, spm))

            warmup_factor = min(1.0, t / 300.0)
            hr = int(base_hr * 0.82 + warmup_factor * (base_hr * 0.18) + (s - target_avg_speed) * 5 * natural_variance + random.randint(-1, 1))
            hr = max(60, min(210, hr))

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
            })

        end_time_utc = records[-1]['timestamp']
        total_elapsed = (end_time_utc - start_time_utc).total_seconds()
        avg_speed = total_dist / total_elapsed
        max_speed = max(r['speed'] for r in records)

        avg_spm_val = int(sum(raw_spms) / len(raw_spms))
        max_spm_val = max(raw_spms)
        if sport == 'running':
            avg_cad_fit = int(round(avg_spm_val / 2.0))
            max_cad_fit = int(round(max_spm_val / 2.0))
        else:
            avg_cad_fit = avg_spm_val
            max_cad_fit = max_spm_val

        avg_hr_val = int(sum(r['heart_rate'] for r in records) / len(records))
        max_hr_val = max(r['heart_rate'] for r in records)

        # Encode FIT
        encoder = Encoder()
        encoder.write_mesg({
            'mesg_num': 0, # file_id
            'type': 'activity',
            'manufacturer': 'strava',
            'product': 101,
            'time_created': start_time_utc,
        })
        encoder.write_mesg({
            'mesg_num': 23, # device_info
            'device_index': 0,
            'manufacturer': 'strava',
            'product': 101,
            'timestamp': start_time_utc,
        })
        encoder.write_mesg({
            'mesg_num': 21, # event start
            'event': 'timer',
            'event_type': 'start',
            'timer_trigger': 'manual',
            'timestamp': start_time_utc,
        })
        for rec in records:
            encoder.write_mesg({'mesg_num': 20, **rec})
        encoder.write_mesg({
            'mesg_num': 21, # event stop
            'event': 'timer',
            'event_type': 'stop',
            'timer_trigger': 'manual',
            'timestamp': end_time_utc,
        })
        encoder.write_mesg({
            'mesg_num': 19, # lap
            'event': 'lap',
            'event_type': 'stop',
            'lap_trigger': 'session_end',
            'sport': sport,
            'sub_sport': sub_sport,
            'start_time': start_time_utc,
            'timestamp': end_time_utc,
            'total_elapsed_time': round(total_elapsed, 3),
            'total_timer_time': round(total_elapsed, 3),
            'total_distance': round(total_dist, 2),
            'avg_speed': round(avg_speed, 3),
            'max_speed': round(max_speed, 3),
            'avg_cadence': avg_cad_fit,
            'max_cadence': max_cad_fit,
            'avg_heart_rate': avg_hr_val,
            'max_heart_rate': max_hr_val,
            'total_ascent': round(total_ascent, 1),
            'total_descent': round(total_descent, 1),
        })
        encoder.write_mesg({
            'mesg_num': 18, # session
            'event': 'session',
            'event_type': 'stop',
            'sport': sport,
            'sub_sport': sub_sport,
            'start_time': start_time_utc,
            'timestamp': end_time_utc,
            'total_elapsed_time': round(total_elapsed, 3),
            'total_timer_time': round(total_elapsed, 3),
            'total_distance': round(total_dist, 2),
            'avg_speed': round(avg_speed, 3),
            'max_speed': round(max_speed, 3),
            'avg_cadence': avg_cad_fit,
            'max_cadence': max_cad_fit,
            'avg_heart_rate': avg_hr_val,
            'max_heart_rate': max_hr_val,
            'total_ascent': round(total_ascent, 1),
            'total_descent': round(total_descent, 1),
            'first_lap_index': 0,
            'num_laps': 1,
        })

        FIT_EPOCH_S = 631065600
        local_ts_int = int(end_time_utc.timestamp()) - FIT_EPOCH_S + int(utc_offset_hours * 3600)
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

        fit_bytes = encoder.close()
        with open(output_path, 'wb') as f:
            f.write(fit_bytes)

        local_end_dt = local_start_dt + datetime.timedelta(seconds=total_elapsed)

        return jsonify({
            'success': True,
            'message': 'Đã tạo file FIT thành công!',
            'filename': out_name,
            'filepath': output_path,
            'file_size_kb': round(len(fit_bytes) / 1024.0, 1),
            'total_records': len(records),
            'start_time_local': local_start_dt.strftime('%H:%M:%S %d/%m/%Y'),
            'end_time_local': local_end_dt.strftime('%H:%M:%S %d/%m/%Y'),
            'duration_formatted': f"{int(total_elapsed//3600):02d}:{int((total_elapsed%3600)//60):02d}:{int(total_elapsed%60):02d}",
            'avg_speed_kmh': round(avg_speed * 3.6, 2),
            'avg_pace': f"{int(avg_pace_min)}:{int((avg_pace_min%1)*60):02d} /km",
            'avg_cadence': avg_spm_val,
            'avg_hr': avg_hr_val,
            'total_distance_km': round(total_dist / 1000.0, 2),
            'total_ascent_m': round(total_ascent, 1),
            'download_url': f'/download/{out_name}'
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/download/<filename>')
def download_file(filename):
    file_path = os.path.join(WORKSPACE_DIR, filename)
    if os.path.exists(file_path):
        return send_file(file_path, as_attachment=True, download_name=filename)
    return "File không tồn tại", 404

def open_browser():
    webbrowser.open_new('http://127.0.0.1:5000/')

if __name__ == '__main__':
    Timer(1.2, open_browser).start()
    print("==================================================")
    print(">> Strava FIT Generator & Editor dang khoi chay...")
    print(">> Mo trinh duyet tai: http://127.0.0.1:5000")
    print("==================================================")
    app.run(host='127.0.0.1', port=5000, debug=False)
