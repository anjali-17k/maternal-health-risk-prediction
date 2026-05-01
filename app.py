from flask import Flask, render_template, request, redirect, url_for, session, flash, make_response
import sqlite3
import os
import pickle
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from reportlab.pdfgen import canvas
from io import BytesIO
from werkzeug.security import generate_password_hash, check_password_hash

#load trained model
model = None
with open(config.MODEL_PATH, 'rb') as f:
    model = pickle.load(f)

app = Flask(__name__)
app.secret_key = config.SECRET_KEY

#Email config
SENDER_EMAIL = config.SENDER_EMAIL
SENDER_PASSWORD = config.SENDER_PASSWORD

#db initialization
def init_db():
    conn = sqlite3.connect(config.DB_PATH)
    c = conn.cursor()

    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL,
            email TEXT
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS health_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            age INTEGER,
            systolic INTEGER,
            diastolic INTEGER,
            bs REAL,
            bodytemp REAL,
            heartrate INTEGER,
            email TEXT,
            risk_level TEXT,
            submitted_at TEXT,
            appointment_id INTEGER,
            FOREIGN KEY (username) REFERENCES users(username)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS clinics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT NOT NULL,
            clinic_name TEXT NOT NULL,
            address TEXT NOT NULL,
            contact_no TEXT,
            email TEXT,
            FOREIGN KEY (provider) REFERENCES users(username)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS doctor_clinics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doctor_username TEXT NOT NULL,
            clinic_id INTEGER NOT NULL,
            status TEXT DEFAULT 'pending',
            FOREIGN KEY (doctor_username) REFERENCES users(username),
            FOREIGN KEY (clinic_id) REFERENCES clinics(id)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_username TEXT NOT NULL,
            doctor_username TEXT NOT NULL,
            clinic_id INTEGER NOT NULL,
            appointment_date TEXT NOT NULL,
            appointment_time TEXT,
            status TEXT DEFAULT 'Pending',
            notes TEXT,
            doctor_notes TEXT,
            finished_at TEXT,
            FOREIGN KEY (patient_username) REFERENCES users(username),
            FOREIGN KEY (doctor_username) REFERENCES users(username),
            FOREIGN KEY (clinic_id) REFERENCES clinics(id)
        )
    ''')

    migrations = [
        "ALTER TABLE users ADD COLUMN email TEXT",
        "ALTER TABLE appointments ADD COLUMN doctor_notes TEXT",
        "ALTER TABLE appointments ADD COLUMN finished_at TEXT",
        "ALTER TABLE health_data ADD COLUMN submitted_at TEXT",
        "ALTER TABLE health_data ADD COLUMN appointment_id INTEGER",
        "ALTER TABLE doctor_clinics ADD COLUMN status TEXT DEFAULT 'pending'",
    ]
    for m in migrations:
        try:
            c.execute(m)
        except sqlite3.OperationalError:
            pass

    c.execute("SELECT * FROM users WHERE username='admin' AND role='admin'")
    if not c.fetchone():
        c.execute("INSERT INTO users (username, password, role, email) VALUES (?, ?, ?, ?)",
                  ('admin', generate_password_hash('123'), 'admin', 'admin@maternalhealth.com'))

    conn.commit()
    conn.close()

init_db()


#email function
def send_email_alert(to_email, clinic_name, patient_name, risk_level, doctor_name=None):
    subject = f"Risk Alert: Patient {patient_name}"
    body = f"""Dear {clinic_name} Team,

This is an automated alert from the Maternal Health System.

Patient: {patient_name}
Risk Level: {risk_level}
{"Associated Doctor: Dr. " + doctor_name if doctor_name else "No doctor assigned yet"}

Please retrieve this patient's contact number from reception and arrange an appointment at your earliest convenience.

Best regards,
Maternal Health System
"""
    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = SENDER_EMAIL
    msg['To'] = to_email

    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, [to_email], msg.as_string())
        server.quit()
    except Exception as e:
        print(f"Failed to send email to {to_email}: {e}")


def send_email(to_email, subject, body):
    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = SENDER_EMAIL
    msg['To'] = to_email
    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, [to_email], msg.as_string())
        server.quit()
    except Exception as e:
        print(f"Failed to send email to {to_email}: {e}")


def email_doctor_risk_alert(doctor_email, doctor_name, patient_name, risk_level):
    send_email(
        doctor_email,
        f"Risk Alert: Your Patient {patient_name}",
        f"""Dear Dr. {doctor_name},

This is an automated alert from the Maternal Health System.

Your patient {patient_name} has submitted a health entry with the following result:

Risk Level: {risk_level}

Please review their health data and follow up at your earliest convenience.

Best regards,
Maternal Health System
"""
    )


def email_patient_appointment_confirmed(patient_email, patient_name, doctor_name, clinic_name, appt_date, appt_time):
    send_email(
        patient_email,
        "Your Appointment Has Been Confirmed",
        f"""Dear {patient_name},

Your appointment has been confirmed. Here are the details:

Doctor: Dr. {doctor_name}
Hospital/Clinic: {clinic_name}
Date: {appt_date}
Time: {appt_time}

Please arrive on time. If you need to cancel, please do so through the platform.

Best regards,
Maternal Health System
"""
    )


def email_patient_appointment_finished(patient_email, patient_name, doctor_name, appt_date, doctor_notes):
    send_email(
        patient_email,
        "Your Appointment Summary",
        f"""Dear {patient_name},

Your consultation with Dr. {doctor_name} on {appt_date} has been completed.

Doctor's Notes:
{doctor_notes if doctor_notes else "No notes provided."}

Please log in to the platform to view your full health records.

Best regards,
Maternal Health System
"""
    )


def email_clinic_doctor_join_request(clinic_email, clinic_name, doctor_username):
    send_email(
        clinic_email,
        "New Doctor Join Request",
        f"""Dear {clinic_name} Team,

A doctor has requested to join your clinic on the Maternal Health Platform.

Doctor Username: {doctor_username}

Please log in to the platform to review and approve or reject this request.

Best regards,
Maternal Health System
"""
    )


def email_doctor_approved(doctor_email, doctor_name, clinic_name):
    send_email(
        doctor_email,
        "Your Clinic Join Request Has Been Approved",
        f"""Dear Dr. {doctor_name},

Congratulations! Your request to join {clinic_name} has been approved.

You can now log in to the platform and start managing your appointments.

Best regards,
Maternal Health System
"""
    )


#routes

@app.route('/')
def home():
    return render_template('auth/home.html')


#register
@app.route('/register/<role>', methods=['GET', 'POST'])
def register(role):
    if role in ['admin', 'clinic']:
        return redirect(url_for('home'))

    clinics = []
    if role == 'doctor':
        conn = sqlite3.connect(config.DB_PATH)
        c = conn.cursor()
        c.execute("SELECT id, clinic_name FROM clinics ORDER BY clinic_name ASC")
        clinics = c.fetchall()
        conn.close()

    if request.method == 'POST':
        username = request.form['username']
        password = generate_password_hash(request.form['password'])
        email = request.form.get('email', '')

        conn = sqlite3.connect(config.DB_PATH)
        c = conn.cursor()
        try:
            c.execute("INSERT INTO users (username, password, role, email) VALUES (?, ?, ?, ?)",
                      (username, password, role, email))
            conn.commit()

            if role == 'doctor':
                clinic_id = request.form.get('clinic_id')
                if clinic_id:
                    c.execute("INSERT INTO doctor_clinics (doctor_username, clinic_id, status) VALUES (?, ?, 'pending')",
                              (username, clinic_id))
                    conn.commit()

            return redirect(url_for('login', role=role))
        except sqlite3.IntegrityError:
            return render_template('auth/register.html', role=role, clinics=clinics, error="Username already exists")
        finally:
            conn.close()

    return render_template('auth/register.html', role=role, clinics=clinics)


#login
@app.route('/login/<role>', methods=['GET', 'POST'])
def login(role):
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = sqlite3.connect(config.DB_PATH)
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE username = ? AND role = ?",
                  (username, role))
        user = c.fetchone()
        conn.close()

        if user and check_password_hash(user[2], password):
            session['username'] = username
            session['role'] = role
            return redirect(url_for('dashboard'))
        else:
            return render_template('auth/login.html', role=role, error="Invalid credentials")
    return render_template('auth/login.html', role=role)


#dashboard
@app.route('/dashboard')
def dashboard():
    if 'username' not in session:
        return redirect(url_for('home'))

    role = session.get('role')
    username = session['username']

    if role == 'pregnant':
        conn = sqlite3.connect(config.DB_PATH)
        c = conn.cursor()
        c.execute("""SELECT COUNT(*) FROM appointments
                     WHERE patient_username=? AND status='Confirmed'""", (username,))
        notif_count = c.fetchone()[0]
        conn.close()
        return render_template('patient/dashboard_pregnant.html', username=username, notif_count=notif_count)

    elif role == 'doctor':
        conn = sqlite3.connect(config.DB_PATH)
        c = conn.cursor()
        c.execute('''
            SELECT dc.status, cl.clinic_name, dc.clinic_id, dc.id
            FROM doctor_clinics dc
            JOIN clinics cl ON dc.clinic_id = cl.id
            WHERE dc.doctor_username = ?
            ORDER BY dc.id DESC LIMIT 1
        ''', (username,))
        clinic_info = c.fetchone()

        #stats for doctor dashboard
        c.execute("SELECT COUNT(DISTINCT patient_username) FROM appointments WHERE doctor_username=?", (username,))
        total_patients = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM appointments WHERE doctor_username=? AND status='Pending'", (username,))
        pending = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM appointments WHERE doctor_username=? AND status='Confirmed'", (username,))
        confirmed = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM appointments WHERE doctor_username=? AND status='Finished'", (username,))
        finished = c.fetchone()[0]

        c.execute("""
            SELECT hd.risk_level, COUNT(*) FROM health_data hd
            JOIN appointments a ON a.patient_username = hd.username
            WHERE a.doctor_username=?
            GROUP BY hd.risk_level
        """, (username,))
        risk_rows = c.fetchall()
        conn.close()

        risk_labels = [r[0] for r in risk_rows]
        risk_counts = [r[1] for r in risk_rows]

        stats = {
            'total_patients': total_patients,
            'pending': pending,
            'confirmed': confirmed,
            'finished': finished,
            'risk_labels': risk_labels,
            'risk_counts': risk_counts,
        }
        return render_template('doctor/dashboard_doctor.html', username=username, clinic_info=clinic_info, stats=stats)

    elif role == 'clinic':
        conn = sqlite3.connect(config.DB_PATH)
        c = conn.cursor()
        c.execute("SELECT id, clinic_name FROM clinics WHERE provider=?", (username,))
        clinic = c.fetchone()

        stats = {'total_doctors': 0, 'total_appointments': 0, 'pending_appointments': 0,
                 'pending_requests': 0, 'confirmed_appointments': 0, 'finished_appointments': 0}

        if clinic:
            clinic_id = clinic[0]
            c.execute("SELECT COUNT(*) FROM doctor_clinics WHERE clinic_id=? AND status='approved'", (clinic_id,))
            stats['total_doctors'] = c.fetchone()[0]

            c.execute("SELECT COUNT(*) FROM appointments WHERE clinic_id=?", (clinic_id,))
            stats['total_appointments'] = c.fetchone()[0]

            c.execute("SELECT COUNT(*) FROM appointments WHERE clinic_id=? AND status='Pending'", (clinic_id,))
            stats['pending_appointments'] = c.fetchone()[0]

            c.execute("SELECT COUNT(*) FROM appointments WHERE clinic_id=? AND status='Confirmed'", (clinic_id,))
            stats['confirmed_appointments'] = c.fetchone()[0]

            c.execute("SELECT COUNT(*) FROM appointments WHERE clinic_id=? AND status='Finished'", (clinic_id,))
            stats['finished_appointments'] = c.fetchone()[0]

            c.execute("SELECT COUNT(*) FROM doctor_clinics WHERE clinic_id=? AND status='pending'", (clinic_id,))
            stats['pending_requests'] = c.fetchone()[0]

        conn.close()
        return render_template('clinic/dashboard_clinic.html', username=username, clinic=clinic, stats=stats)

    elif role == 'admin':
        conn = sqlite3.connect(config.DB_PATH)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM clinics")
        total_clinics = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM users WHERE role='pregnant'")
        total_patients = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM users WHERE role='doctor'")
        total_doctors = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM appointments")
        total_appointments = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM appointments WHERE status='Finished'")
        finished_appointments = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM appointments WHERE status='Pending'")
        pending_appointments = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM appointments WHERE status='Confirmed'")
        confirmed_appointments = c.fetchone()[0]
        c.execute('''
            SELECT cl.clinic_name, COUNT(a.id)
            FROM clinics cl
            LEFT JOIN appointments a ON a.clinic_id = cl.id
            GROUP BY cl.id ORDER BY COUNT(a.id) DESC
        ''')
        clinic_appointment_data = c.fetchall()
        c.execute('''
            SELECT risk_level, COUNT(*) FROM health_data
            WHERE risk_level IS NOT NULL GROUP BY risk_level
        ''')
        risk_data = c.fetchall()
        conn.close()
        clinic_names = [r[0] for r in clinic_appointment_data]
        clinic_counts = [r[1] for r in clinic_appointment_data]
        risk_labels = [r[0] for r in risk_data]
        risk_counts = [r[1] for r in risk_data]
        return render_template('admin/dashboard_admin.html', username=username,
                               total_clinics=total_clinics, total_patients=total_patients,
                               total_doctors=total_doctors, total_appointments=total_appointments,
                               finished_appointments=finished_appointments,
                               pending_appointments=pending_appointments,
                               confirmed_appointments=confirmed_appointments,
                               clinic_names=clinic_names, clinic_counts=clinic_counts,
                               risk_labels=risk_labels, risk_counts=risk_counts)

    return redirect(url_for('home'))


#health entry
@app.route('/health-entry', methods=['GET', 'POST'])
def health_entry():
    if 'username' not in session or session.get('role') != 'pregnant':
        return redirect(url_for('login', role='pregnant'))

    if request.method == 'POST':
        age = int(request.form['age'])
        systolic = int(request.form['systolic'])
        diastolic = int(request.form['diastolic'])
        bs = float(request.form['bs'])
        bodytemp = float(request.form['bodytemp'])
        heartrate = int(request.form['heartrate'])
        email = request.form['email']
        username = session['username']
        submitted_at = datetime.now().strftime('%Y-%m-%d %H:%M')

        pred = model.predict([[age, systolic, diastolic, bs, bodytemp, heartrate]])[0]
        risk_map = {0: 'High Risk', 1: 'Low Risk', 2: 'Moderate Risk'}
        risk_level = risk_map.get(int(pred), 'Unknown')

        conn = sqlite3.connect(config.DB_PATH)
        c = conn.cursor()
        c.execute('''
            INSERT INTO health_data (username, age, systolic, diastolic, bs, bodytemp, heartrate, email, risk_level, submitted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (username, age, systolic, diastolic, bs, bodytemp, heartrate, email, risk_level, submitted_at))
        conn.commit()

        if risk_level in ['High Risk', 'Moderate Risk']:
            c2 = conn.cursor()
            c2.execute('''
                SELECT cl.clinic_name, cl.email, a.doctor_username
                FROM appointments a
                JOIN clinics cl ON a.clinic_id = cl.id
                WHERE a.patient_username = ?
                ORDER BY a.id DESC LIMIT 1
            ''', (username,))
            clinic = c2.fetchone()

            if clinic and clinic[1]:
                send_email_alert(clinic[1], clinic[0], username, risk_level, clinic[2])

            # Email #2 — notify doctor
            if clinic and clinic[2]:
                c2.execute("SELECT email FROM users WHERE username=?", (clinic[2],))
                doc = c2.fetchone()
                if doc and doc[0]:
                    email_doctor_risk_alert(doc[0], clinic[2], username, risk_level)

        conn.close()
        return redirect(url_for('my_results'))

    return render_template('patient/health_entry.html')


#doctor view patients
@app.route('/doctor/view-patients')
def view_patients():
    if 'username' not in session or session.get('role') != 'doctor':
        return redirect(url_for('login', role='doctor'))

    conn = sqlite3.connect(config.DB_PATH)
    username = session['username']
    c = conn.cursor()
    c.execute("""SELECT DISTINCT hd.* FROM health_data hd
             JOIN appointments a ON a.patient_username = hd.username
             WHERE a.doctor_username = ?""", (username,))
    patients = c.fetchall()
    conn.close()

    results = []
    for p in patients:
        results.append({
            'id': p[0], 'username': p[1], 'age': p[2],
            'systolic': p[3], 'diastolic': p[4], 'bs': p[5],
            'bodytemp': p[6], 'heartrate': p[7], 'email': p[8],
            'risk_level': p[9] if p[9] else 'Unknown'
        })

    return render_template('doctor/doctor_view.html', patients=results)


#chatbot
@app.route('/chatbot')
def chatbot():
    if 'username' not in session or session.get('role') != 'pregnant':
        return redirect(url_for('login', role='pregnant'))
    return render_template('patient/chatbot.html')


#appointments (patient)
@app.route('/appointments', methods=['GET', 'POST'])
def appointments():
    if 'username' not in session or session.get('role') != 'pregnant':
        return redirect(url_for('login', role='pregnant'))

    username = session['username']
    conn = sqlite3.connect(config.DB_PATH)
    c = conn.cursor()

    c.execute('''
        SELECT u.username, cl.clinic_name, dc.clinic_id
        FROM users u
        JOIN doctor_clinics dc ON u.username = dc.doctor_username
        JOIN clinics cl ON dc.clinic_id = cl.id
        WHERE u.role = 'doctor' AND dc.status = 'approved'
        ORDER BY cl.clinic_name, u.username ASC
    ''')
    doctors = c.fetchall()

    c.execute("SELECT id, clinic_name FROM clinics ORDER BY clinic_name ASC")
    clinics = c.fetchall()

    if request.method == 'POST':
        doctor_username = request.form['doctor']
        clinic_id = request.form['clinic']
        appointment_date = request.form['date']
        appointment_time = request.form['time']
        notes = request.form.get('notes', '')

        c.execute('''
            INSERT INTO appointments (patient_username, doctor_username, clinic_id, appointment_date, appointment_time, notes)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (username, doctor_username, clinic_id, appointment_date, appointment_time, notes))
        conn.commit()
        conn.close()
        flash('Appointment booked successfully!', 'success')
        return redirect(url_for('appointments'))

    c.execute('''
        SELECT a.id, a.doctor_username, cl.clinic_name, a.appointment_date, a.appointment_time, a.status, a.notes
        FROM appointments a
        JOIN clinics cl ON a.clinic_id = cl.id
        WHERE a.patient_username = ? AND a.status IN ('Pending', 'Confirmed')
        ORDER BY a.appointment_date ASC
    ''', (username,))
    upcoming = c.fetchall()

    c.execute('''
        SELECT a.id, a.doctor_username, cl.clinic_name, a.appointment_date, a.appointment_time,
               a.finished_at, a.doctor_notes,
               h.age, h.systolic, h.diastolic, h.bs, h.bodytemp, h.heartrate, h.risk_level, h.submitted_at
        FROM appointments a
        JOIN clinics cl ON a.clinic_id = cl.id
        LEFT JOIN health_data h ON h.appointment_id = a.id
        WHERE a.patient_username = ? AND a.status = 'Finished'
        ORDER BY a.finished_at DESC
    ''', (username,))
    past_visits = c.fetchall()
    conn.close()

    return render_template('patient/appointments.html',
                           doctors=doctors, clinics=clinics,
                           upcoming=upcoming, past_visits=past_visits)


#cancel appointment
@app.route('/appointments/cancel/<int:appointment_id>', methods=['POST'])
def cancel_appointment(appointment_id):
    if 'username' not in session or session.get('role') != 'pregnant':
        return redirect(url_for('login', role='pregnant'))

    conn = sqlite3.connect(config.DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM appointments WHERE id=? AND patient_username=? AND status='Pending'",
              (appointment_id, session['username']))
    conn.commit()
    conn.close()
    flash('Appointment cancelled.', 'info')
    return redirect(url_for('appointments'))


#link health result
@app.route('/appointments/<int:appointment_id>/link-result', methods=['POST'])
def link_result_to_appointment(appointment_id):
    if 'username' not in session or session.get('role') != 'pregnant':
        return redirect(url_for('login', role='pregnant'))

    username = session['username']
    conn = sqlite3.connect(config.DB_PATH)
    c = conn.cursor()
    c.execute('''
        UPDATE health_data SET appointment_id=?
        WHERE id = (
            SELECT id FROM health_data
            WHERE username=? AND (appointment_id IS NULL OR appointment_id=0)
            ORDER BY id DESC LIMIT 1
        )
    ''', (appointment_id, username))
    conn.commit()
    conn.close()
    flash('Health result linked to appointment!', 'success')
    return redirect(url_for('appointments'))


#doctor appointments
@app.route('/doctor/appointments')
def doctor_appointments():
    if 'username' not in session or session.get('role') != 'doctor':
        return redirect(url_for('login', role='doctor'))

    username = session['username']
    conn = sqlite3.connect(config.DB_PATH)
    c = conn.cursor()

    c.execute('''
        SELECT a.id, a.patient_username, cl.clinic_name, a.appointment_date, a.appointment_time, a.notes
        FROM appointments a JOIN clinics cl ON a.clinic_id = cl.id
        WHERE a.doctor_username = ? AND a.status = 'Pending'
        ORDER BY a.appointment_date ASC
    ''', (username,))
    pending = c.fetchall()

    c.execute('''
        SELECT a.id, a.patient_username, cl.clinic_name, a.appointment_date, a.appointment_time, a.notes
        FROM appointments a JOIN clinics cl ON a.clinic_id = cl.id
        WHERE a.doctor_username = ? AND a.status = 'Confirmed'
        ORDER BY a.appointment_date ASC
    ''', (username,))
    confirmed = c.fetchall()

    c.execute('''
        SELECT a.id, a.patient_username, cl.clinic_name, a.appointment_date,
               a.finished_at, a.doctor_notes,
               h.age, h.systolic, h.diastolic, h.bs, h.bodytemp, h.heartrate, h.risk_level, h.submitted_at
        FROM appointments a JOIN clinics cl ON a.clinic_id = cl.id
        LEFT JOIN health_data h ON h.appointment_id = a.id
        WHERE a.doctor_username = ? AND a.status = 'Finished'
        ORDER BY a.finished_at DESC
    ''', (username,))
    finished = c.fetchall()
    conn.close()

    return render_template('doctor/doctor_appointments.html',
                           pending=pending, confirmed=confirmed, finished=finished)


#confirm appointment (doctor)
@app.route('/doctor/appointments/confirm/<int:appointment_id>', methods=['POST'])
def confirm_appointment(appointment_id):
    if 'username' not in session or session.get('role') != 'doctor':
        return redirect(url_for('login', role='doctor'))

    conn = sqlite3.connect(config.DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE appointments SET status='Confirmed' WHERE id=? AND doctor_username=?",
              (appointment_id, session['username']))
    conn.commit()

    # Email notify patient
    c.execute('''
        SELECT a.patient_username, a.appointment_date, a.appointment_time, cl.clinic_name, u.email
        FROM appointments a
        JOIN clinics cl ON a.clinic_id = cl.id
        JOIN users u ON u.username = a.patient_username
        WHERE a.id=?
    ''', (appointment_id,))
    row = c.fetchone()
    if row and row[4]:
        email_patient_appointment_confirmed(row[4], row[0], session['username'], row[3], row[1], row[2])

    conn.close()
    flash('Appointment confirmed!', 'success')
    return redirect(url_for('doctor_appointments'))


#finish appointment (doctor)
@app.route('/doctor/appointments/finish/<int:appointment_id>', methods=['POST'])
def doctor_finish_appointment(appointment_id):
    if 'username' not in session or session.get('role') != 'doctor':
        return redirect(url_for('login', role='doctor'))

    doctor_notes = request.form.get('doctor_notes', '')
    finished_at = datetime.now().strftime('%Y-%m-%d %H:%M')

    conn = sqlite3.connect(config.DB_PATH)
    c = conn.cursor()
    c.execute('''
        UPDATE appointments SET status='Finished', finished_at=?, doctor_notes=?
        WHERE id=? AND doctor_username=?
    ''', (finished_at, doctor_notes, appointment_id, session['username']))
    conn.commit()

    # Email notify patient appointment finished
    c.execute('''
        SELECT a.patient_username, a.appointment_date, u.email
        FROM appointments a
        JOIN users u ON u.username = a.patient_username
        WHERE a.id=?
    ''', (appointment_id,))
    row = c.fetchone()
    if row and row[2]:
        email_patient_appointment_finished(row[2], row[0], session['username'], row[1], doctor_notes)

    conn.close()
    flash('Appointment marked as finished!', 'success')
    return redirect(url_for('doctor_appointments'))


#doc leave clinic
@app.route('/doctor/leave-clinic', methods=['POST'])
def doctor_leave_clinic():
    if 'username' not in session or session.get('role') != 'doctor':
        return redirect(url_for('login', role='doctor'))

    conn = sqlite3.connect(config.DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM doctor_clinics WHERE doctor_username=?", (session['username'],))
    conn.commit()
    conn.close()
    flash('You have left your clinic. You can now join a new one.', 'info')
    return redirect(url_for('doctor_join_clinic'))


#doc join clinic
@app.route('/doctor/join-clinic', methods=['GET', 'POST'])
def doctor_join_clinic():
    if 'username' not in session or session.get('role') != 'doctor':
        return redirect(url_for('login', role='doctor'))

    username = session['username']
    conn = sqlite3.connect(config.DB_PATH)
    c = conn.cursor()

    c.execute("SELECT * FROM doctor_clinics WHERE doctor_username=?", (username,))
    existing = c.fetchone()
    if existing:
        conn.close()
        flash('You are already linked to a clinic. Leave it first before joining another.', 'info')
        return redirect(url_for('dashboard'))

    c.execute("SELECT id, clinic_name, address FROM clinics ORDER BY clinic_name ASC")
    clinics = c.fetchall()

    if request.method == 'POST':
        clinic_id = request.form['clinic_id']
        c.execute("INSERT INTO doctor_clinics (doctor_username, clinic_id, status) VALUES (?, ?, 'pending')",
                  (username, clinic_id))
        conn.commit()

        # Email notify hospital of join request
        c.execute("SELECT cl.clinic_name, u.email FROM clinics cl JOIN users u ON u.username = cl.provider WHERE cl.id=?", (clinic_id,))
        clinic_row = c.fetchone()
        if clinic_row and clinic_row[1]:
            email_clinic_doctor_join_request(clinic_row[1], clinic_row[0], username)

        conn.close()
        flash('Join request sent! Waiting for clinic approval.', 'success')
        return redirect(url_for('dashboard'))

    conn.close()
    return render_template('doctor/doctor_join_clinic.html', clinics=clinics)


#clinic manage doc
@app.route('/clinic/doctors')
def clinic_doctors():
    if 'username' not in session or session.get('role') != 'clinic':
        return redirect(url_for('login', role='clinic'))

    username = session['username']
    conn = sqlite3.connect(config.DB_PATH)
    c = conn.cursor()

    c.execute("SELECT id FROM clinics WHERE provider=?", (username,))
    clinic_row = c.fetchone()
    if not clinic_row:
        conn.close()
        return redirect(url_for('dashboard'))

    clinic_id = clinic_row[0]

    c.execute('''
        SELECT dc.id, dc.doctor_username, u.email, dc.status
        FROM doctor_clinics dc
        JOIN users u ON dc.doctor_username = u.username
        WHERE dc.clinic_id = ?
        ORDER BY dc.status ASC, dc.doctor_username ASC
    ''', (clinic_id,))
    doctors = c.fetchall()
    conn.close()

    return render_template('clinic/clinic_doctors.html', doctors=doctors)


@app.route('/clinic/doctors/approve/<int:dc_id>', methods=['POST'])
def clinic_approve_doctor(dc_id):
    if 'username' not in session or session.get('role') != 'clinic':
        return redirect(url_for('login', role='clinic'))

    conn = sqlite3.connect(config.DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT cl.provider, dc.doctor_username, cl.clinic_name
        FROM doctor_clinics dc
        JOIN clinics cl ON dc.clinic_id = cl.id
        WHERE dc.id=?
    ''', (dc_id,))
    row = c.fetchone()
    if row and row[0] == session['username']:
        c.execute("UPDATE doctor_clinics SET status='approved' WHERE id=?", (dc_id,))
        conn.commit()
        flash('Doctor approved!', 'success')

        # Email notify doctor of approval
        c.execute("SELECT email FROM users WHERE username=?", (row[1],))
        doc = c.fetchone()
        if doc and doc[0]:
            email_doctor_approved(doc[0], row[1], row[2])

    conn.close()
    return redirect(url_for('clinic_doctors'))


@app.route('/clinic/doctors/remove/<int:dc_id>', methods=['POST'])
def clinic_remove_doctor(dc_id):
    if 'username' not in session or session.get('role') != 'clinic':
        return redirect(url_for('login', role='clinic'))

    conn = sqlite3.connect(config.DB_PATH)
    c = conn.cursor()
    c.execute("SELECT cl.provider FROM doctor_clinics dc JOIN clinics cl ON dc.clinic_id = cl.id WHERE dc.id=?", (dc_id,))
    row = c.fetchone()
    if row and row[0] == session['username']:
        c.execute("DELETE FROM doctor_clinics WHERE id=?", (dc_id,))
        conn.commit()
        flash('Doctor removed from clinic.', 'info')
    conn.close()
    return redirect(url_for('clinic_doctors'))


#admin manage clinic
@app.route('/admin/clinics')
def admin_clinics():
    if 'username' not in session or session.get('role') != 'admin':
        return redirect(url_for('login', role='admin'))

    conn = sqlite3.connect(config.DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT cl.id, cl.clinic_name, cl.address, cl.contact_no, cl.email, cl.provider,
               COUNT(dc.id) as doctor_count
        FROM clinics cl
        LEFT JOIN doctor_clinics dc ON dc.clinic_id = cl.id AND dc.status = 'approved'
        GROUP BY cl.id
        ORDER BY cl.clinic_name ASC
    ''')
    clinics = c.fetchall()
    conn.close()
    return render_template('admin/admin_clinics.html', clinics=clinics)


@app.route('/admin/clinics/add', methods=['POST'])
def admin_add_clinic():
    if 'username' not in session or session.get('role') != 'admin':
        return redirect(url_for('login', role='admin'))

    clinic_name = request.form['clinic_name']
    address = request.form['address']
    contact_no = request.form['contact_no']
    email = request.form['email']
    clinic_username = request.form['clinic_username']
    clinic_password = request.form['clinic_password']

    conn = sqlite3.connect(config.DB_PATH)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (username, password, role, email) VALUES (?, ?, 'clinic', ?)",
                  (clinic_username, generate_password_hash(clinic_password), email))
        c.execute('''
            INSERT INTO clinics (provider, clinic_name, address, contact_no, email)
            VALUES (?, ?, ?, ?, ?)
        ''', (clinic_username, clinic_name, address, contact_no, email))
        conn.commit()
        flash(f'Hospital/Clinic "{clinic_name}" registered successfully!', 'success')
    except sqlite3.IntegrityError:
        flash('Username already exists. Choose a different clinic username.', 'danger')
    finally:
        conn.close()

    return redirect(url_for('admin_clinics'))


@app.route('/admin/clinics/delete/<int:clinic_id>', methods=['POST'])
def admin_delete_clinic(clinic_id):
    if 'username' not in session or session.get('role') != 'admin':
        return redirect(url_for('login', role='admin'))

    conn = sqlite3.connect(config.DB_PATH)
    c = conn.cursor()
    c.execute("SELECT provider FROM clinics WHERE id=?", (clinic_id,))
    row = c.fetchone()
    if row:
        c.execute("DELETE FROM doctor_clinics WHERE clinic_id=?", (clinic_id,))
        c.execute("DELETE FROM clinics WHERE id=?", (clinic_id,))
        c.execute("DELETE FROM users WHERE username=? AND role='clinic'", (row[0],))
        conn.commit()
        flash('Hospital removed successfully.', 'info')
    conn.close()
    return redirect(url_for('admin_clinics'))


#admin analytics
@app.route('/admin/analytics')
def admin_analytics():
    if 'username' not in session or session.get('role') != 'admin':
        return redirect(url_for('login', role='admin'))

    conn = sqlite3.connect(config.DB_PATH)
    c = conn.cursor()

    c.execute("SELECT COUNT(*) FROM clinics")
    total_clinics = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM users WHERE role='pregnant'")
    total_patients = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM users WHERE role='doctor'")
    total_doctors = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM appointments")
    total_appointments = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM appointments WHERE status='Finished'")
    finished_appointments = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM appointments WHERE status='Pending'")
    pending_appointments = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM appointments WHERE status='Confirmed'")
    confirmed_appointments = c.fetchone()[0]

    c.execute('''
        SELECT cl.clinic_name, COUNT(a.id)
        FROM clinics cl
        LEFT JOIN appointments a ON a.clinic_id = cl.id
        GROUP BY cl.id
        ORDER BY COUNT(a.id) DESC
    ''')
    clinic_appointment_data = c.fetchall()

    c.execute('''
        SELECT risk_level, COUNT(*) FROM health_data
        WHERE risk_level IS NOT NULL
        GROUP BY risk_level
    ''')
    risk_data = c.fetchall()

    conn.close()

    clinic_names = [r[0] for r in clinic_appointment_data]
    clinic_counts = [r[1] for r in clinic_appointment_data]
    risk_labels = [r[0] for r in risk_data]
    risk_counts = [r[1] for r in risk_data]

    return render_template('admin/admin_analytics.html',
                           total_clinics=total_clinics,
                           total_patients=total_patients,
                           total_doctors=total_doctors,
                           total_appointments=total_appointments,
                           finished_appointments=finished_appointments,
                           pending_appointments=pending_appointments,
                           confirmed_appointments=confirmed_appointments,
                           clinic_names=clinic_names,
                           clinic_counts=clinic_counts,
                           risk_labels=risk_labels,
                           risk_counts=risk_counts)


#admin profile update
@app.route('/admin/profile/view')
def admin_view_profile():
    if 'username' not in session or session.get('role') != 'admin':
        return redirect(url_for('login', role='admin'))

    conn = sqlite3.connect(config.DB_PATH)
    c = conn.cursor()
    c.execute("SELECT username, email FROM users WHERE username='admin'")
    row = c.fetchone()
    conn.close()
    admin_username = row[0] if row else 'admin'
    admin_email = row[1] if row else ''
    return render_template('admin/admin_view_profile.html', admin_username=admin_username, admin_email=admin_email)


@app.route('/admin/profile', methods=['GET', 'POST'])
def admin_profile():
    if 'username' not in session or session.get('role') != 'admin':
        return redirect(url_for('login', role='admin'))

    conn = sqlite3.connect(config.DB_PATH)
    c = conn.cursor()

    if request.method == 'POST':
        new_email = request.form.get('email', '')
        new_password = request.form.get('password', '')
        if new_password:
            c.execute("UPDATE users SET email=?, password=? WHERE username='admin'",
                      (new_email, generate_password_hash(new_password)))
        else:
            c.execute("UPDATE users SET email=? WHERE username='admin'", (new_email,))
        conn.commit()
        flash('Admin profile updated!', 'success')
        conn.close()
        return redirect(url_for('admin_profile'))

    c.execute("SELECT email FROM users WHERE username='admin'")
    row = c.fetchone()
    conn.close()
    admin_email = row[0] if row else ''
    return render_template('admin/admin_profile.html', admin_email=admin_email)


#suggestion
def get_suggestions(risk_level):
    if risk_level == 'High Risk':
        return [
            "Consult your doctor immediately.",
            "Avoid strenuous physical activity.",
            "Maintain a healthy diet low in salt and sugar.",
            "Monitor your blood pressure regularly."
        ]
    elif risk_level == 'Moderate Risk':
        return [
            "Follow your prescribed medication schedule.",
            "Incorporate moderate exercise into your routine.",
            "Reduce stress through mindfulness or yoga.",
            "Schedule regular checkups with your healthcare provider."
        ]
    else:
        return [
            "Maintain a balanced diet and exercise regularly.",
            "Get regular health checkups.",
            "Avoid smoking and limit alcohol consumption.",
            "Stay hydrated and get adequate rest."
        ]


#view results
@app.route('/view_results')
def view_results():
    if 'username' not in session:
        return redirect(url_for('home'))
    username = request.args.get('username')
    if not username:
        return "Please specify username in URL query ?username=..."
    if username != session['username'] and session.get('role') != 'doctor':
        return redirect(url_for('home'))

    conn = sqlite3.connect(config.DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT age, systolic, diastolic, bs, bodytemp, heartrate, risk_level
        FROM health_data WHERE username = ? ORDER BY id DESC LIMIT 1
    ''', (username,))
    result = c.fetchone()
    conn.close()

    if not result:
        return "No health data available for user: " + username

    age, systolic, diastolic, bs, bodytemp, heartrate, risk_level = result
    suggestions = get_suggestions(risk_level)

    return render_template('patient/patient_results.html',
                           username=username,
                           age=age, systolic=systolic, diastolic=diastolic,
                           bs=bs, bodytemp=bodytemp, heartrate=heartrate,
                           risk_level=risk_level, suggestions=suggestions)


#my results
@app.route('/my-results')
def my_results():
    if 'username' not in session or session.get('role') != 'pregnant':
        return redirect(url_for('login', role='pregnant'))

    username = session['username']
    conn = sqlite3.connect(config.DB_PATH)
    c = conn.cursor()

    c.execute('''
        SELECT age, systolic, diastolic, bs, bodytemp, heartrate, risk_level, submitted_at
        FROM health_data WHERE username = ?
        ORDER BY id DESC LIMIT 1
    ''', (username,))
    row = c.fetchone()

    c.execute('''
        SELECT id, age, systolic, diastolic, bs, bodytemp, heartrate, risk_level, submitted_at
        FROM health_data WHERE username = ?
        ORDER BY id DESC
    ''', (username,))
    history_rows = c.fetchall()
    conn.close()

    result = None
    suggestions = []
    if row:
        result = {
            'age': row[0], 'systolic': row[1], 'diastolic': row[2],
            'bs': row[3], 'bodytemp': row[4], 'heartrate': row[5],
            'risk_level': row[6], 'submitted_at': row[7]
        }
        suggestions = get_suggestions(result['risk_level'])

    history = []
    for h in history_rows:
        history.append({
            'id': h[0], 'age': h[1], 'systolic': h[2], 'diastolic': h[3],
            'bs': h[4], 'bodytemp': h[5], 'heartrate': h[6],
            'risk_level': h[7], 'submitted_at': h[8]
        })

    return render_template('patient/my_results.html', result=result, suggestions=suggestions, history=history)


#dwnld pdf
@app.route('/download_pdf', methods=['POST'])
def download_pdf():
    if 'username' not in session:
        return redirect(url_for('login', role='pregnant'))

    conn = sqlite3.connect(config.DB_PATH)
    c = conn.cursor()
    c.execute('SELECT age, systolic, diastolic, bs, bodytemp, heartrate, risk_level FROM health_data WHERE username = ? ORDER BY id DESC LIMIT 1', (session['username'],))
    result = c.fetchone()
    conn.close()

    if not result:
        return "No data to generate report."

    age, systolic, diastolic, bs, bodytemp, heartrate, risk_level = result
    suggestions = get_suggestions(risk_level)

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer)
    pdf.setTitle(f"{session['username']}_Health_Report")
    pdf.drawString(100, 800, f"Health Report for {session['username']}")
    pdf.drawString(100, 780, f"Age: {age}")
    pdf.drawString(100, 765, f"Systolic: {systolic}")
    pdf.drawString(100, 750, f"Diastolic: {diastolic}")
    pdf.drawString(100, 735, f"Blood Sugar: {bs}")
    pdf.drawString(100, 720, f"Body Temp: {bodytemp}")
    pdf.drawString(100, 705, f"Heart Rate: {heartrate}")
    pdf.drawString(100, 690, f"Risk Level: {risk_level}")
    pdf.drawString(100, 660, "Precautions/Suggestions:")
    y = 645
    for s in suggestions:
        pdf.drawString(120, y, f"- {s}")
        y -= 15

    pdf.showPage()
    pdf.save()
    buffer.seek(0)

    response = make_response(buffer.read())
    response.headers['Content-Disposition'] = f'attachment; filename={session["username"]}_Health_Report.pdf'
    response.mimetype = 'application/pdf'
    return response


#doc profile
@app.route('/doctor/profile', methods=['GET', 'POST'])
def doctor_profile():
    if 'username' not in session or session.get('role') != 'doctor':
        return redirect(url_for('login', role='doctor'))
    username = session['username']
    conn = sqlite3.connect(config.DB_PATH)
    c = conn.cursor()
    if request.method == 'POST':
        new_email = request.form.get('email', '')
        new_password = request.form.get('password', '')
        if new_password:
            c.execute("UPDATE users SET email=?, password=? WHERE username=?",
                      (new_email, generate_password_hash(new_password), username))
        else:
            c.execute("UPDATE users SET email=? WHERE username=?", (new_email, username))
        conn.commit()
        flash('Profile updated!', 'success')
        conn.close()
        return redirect(url_for('doctor_profile'))
    c.execute("SELECT username, email FROM users WHERE username=?", (username,))
    row = c.fetchone()
    conn.close()
    return render_template('doctor/doctor_profile.html', username=row[0], email=row[1] or '')


#patient profile
@app.route('/patient/profile', methods=['GET', 'POST'])
def patient_profile():
    if 'username' not in session or session.get('role') != 'pregnant':
        return redirect(url_for('login', role='pregnant'))
    username = session['username']
    conn = sqlite3.connect(config.DB_PATH)
    c = conn.cursor()
    if request.method == 'POST':
        new_email = request.form.get('email', '')
        new_password = request.form.get('password', '')
        if new_password:
            c.execute("UPDATE users SET email=?, password=? WHERE username=?",
                      (new_email, generate_password_hash(new_password), username))
        else:
            c.execute("UPDATE users SET email=? WHERE username=?", (new_email, username))
        conn.commit()
        flash('Profile updated!', 'success')
        conn.close()
        return redirect(url_for('patient_profile'))
    c.execute("SELECT username, email FROM users WHERE username=?", (username,))
    row = c.fetchone()
    conn.close()
    return render_template('patient/patient_profile.html', username=row[0], email=row[1] or '')


#logout
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))
