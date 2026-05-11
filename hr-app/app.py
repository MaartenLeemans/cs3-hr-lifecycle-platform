from flask import Flask, render_template, request, redirect, session, Response
import psycopg2
import requests
from ldap3 import Server, Connection, ALL, SUBTREE
from datetime import datetime
import os

app = Flask(__name__)
app.secret_key = os.getenv("APP_SECRET_KEY", "ChangeThisSecretKey123")

DB_HOST = os.getenv("DB_HOST", "192.168.10.30")
DB_NAME = os.getenv("DB_NAME", "hr_lifecycle")
DB_USER = os.getenv("DB_USER", "hr_admin")
DB_PASSWORD = os.getenv("DB_PASSWORD", "StrongPassword123!")

AD_SERVER = os.getenv("AD_SERVER", "192.168.10.10")
AD_DOMAIN = os.getenv("AD_DOMAIN", "innovatech.local")
AD_USERS_OU = os.getenv("AD_USERS_OU", "OU=Employees,OU=Innovatech,DC=innovatech,DC=local")

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "YOUR_TOKEN_HERE")
GITHUB_REPO = os.getenv("GITHUB_REPO", "MaartenLeemans/cs3-hr-lifecycle-platform")


def db():
    return psycopg2.connect(
        host=DB_HOST,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD
    )


def logged_in():
    return "username" in session and "password" in session


def ad_login(username, password):
    try:
        server = Server(AD_SERVER, get_info=ALL)
        user = f"{username}@{AD_DOMAIN}"
        conn = Connection(server, user=user, password=password, auto_bind=True)
        conn.unbind()
        return True
    except Exception as e:
        print(f"AD login error: {e}")
        return False


def get_ad_users():
    users = []

    try:
        server = Server(AD_SERVER, get_info=ALL)
        user = f"{session['username']}@{AD_DOMAIN}"
        password = session["password"]

        conn = Connection(server, user=user, password=password, auto_bind=True)

        conn.search(
            search_base=AD_USERS_OU,
            search_filter="(objectClass=user)",
            search_scope=SUBTREE,
            attributes=["cn", "mail", "department", "title", "sAMAccountName", "userAccountControl"]
        )

        for entry in conn.entries:
            try:
                uac = int(entry.userAccountControl.value)
                disabled = bool(uac & 2)
            except Exception:
                disabled = False

            sam = str(entry.sAMAccountName) if entry.sAMAccountName else ""
            email = str(entry.mail) if entry.mail else f"{sam}@innovatech.local"

            users.append({
                "name": str(entry.cn) if entry.cn else sam,
                "email": email,
                "department": str(entry.department) if entry.department else "",
                "role": str(entry.title) if entry.title else "",
                "sam": sam,
                "ad_status": "Disabled" if disabled else "Enabled"
            })

        conn.unbind()

    except Exception as e:
        print(f"LDAP search error: {e}")

    return users


def get_db_status_by_sam(sam):
    email = f"{sam}@innovatech.local"

    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT id,status FROM employees WHERE email=%s ORDER BY id DESC LIMIT 1", (email,))
    result = cur.fetchone()
    cur.close()
    conn.close()

    if result:
        return result[0], result[1]

    return None, "Not tracked"


def log_event(employee_id, action, message):
    conn = db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO lifecycle_events (employee_id, action, message, created_at) VALUES (%s,%s,%s,%s)",
        (employee_id, action, message, datetime.now())
    )
    conn.commit()
    cur.close()
    conn.close()


def trigger_workflow(workflow, inputs):
    url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/{workflow}/dispatches"

    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }

    payload = {
        "ref": "main",
        "inputs": inputs
    }

    response = requests.post(url, json=payload, headers=headers)
    return response.status_code


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None

    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        if ad_login(username, password):
            session["username"] = username
            session["password"] = password
            return redirect("/")
        else:
            error = "Invalid Active Directory login"

    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.route("/")
def index():
    if not logged_in():
        return redirect("/login")

    ad_users = get_ad_users()
    enriched_users = []

    for user in ad_users:
        db_id, db_status = get_db_status_by_sam(user["sam"])
        user["db_id"] = db_id
        user["db_status"] = db_status
        enriched_users.append(user)

    return render_template("index.html", users=enriched_users, username=session["username"])


@app.route("/add", methods=["POST"])
def add_employee():
    if not logged_in():
        return redirect("/login")

    name = request.form["name"]
    email = request.form["email"]
    department = request.form["department"]
    role = request.form["role"]

    conn = db()
    cur = conn.cursor()

    cur.execute(
        "INSERT INTO employees (name, email, department, status, role) VALUES (%s,%s,%s,%s,%s) RETURNING id",
        (name, email, department, "Onboarding Requested", role)
    )

    employee_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()

    status = trigger_workflow("onboarding.yml", {
        "name": name,
        "email": email,
        "department": department,
        "role": role
    })

    log_event(
        employee_id,
        "ONBOARDING_REQUESTED",
        f"AD user creation triggered by {session['username']}. GitHub API status: {status}"
    )

    return redirect("/")


@app.route("/offboard/<sam>")
def offboard(sam):
    if not logged_in():
        return redirect("/login")

    email = f"{sam}@innovatech.local"

    conn = db()
    cur = conn.cursor()

    cur.execute("SELECT id FROM employees WHERE email=%s ORDER BY id DESC LIMIT 1", (email,))
    result = cur.fetchone()

    if result:
        employee_id = result[0]
        cur.execute("UPDATE employees SET status='Offboarding Requested' WHERE id=%s", (employee_id,))
    else:
        cur.execute(
            "INSERT INTO employees (name, email, department, status, role) VALUES (%s,%s,%s,%s,%s) RETURNING id",
            (sam, email, "Unknown", "Offboarding Requested", "Unknown")
        )
        employee_id = cur.fetchone()[0]

    conn.commit()
    cur.close()
    conn.close()

    status = trigger_workflow("offboarding.yml", {
        "samAccountName": sam
    })

    log_event(
        employee_id,
        "OFFBOARDING_REQUESTED",
        f"AD user offboarding triggered by {session['username']}. GitHub API status: {status}"
    )

    return redirect("/")


@app.route("/events/<int:id>")
def events(id):
    if not logged_in():
        return redirect("/login")

    conn = db()
    cur = conn.cursor()

    cur.execute(
        "SELECT action,message,created_at FROM lifecycle_events WHERE employee_id=%s ORDER BY created_at DESC",
        (id,)
    )

    events = cur.fetchall()
    cur.close()
    conn.close()

    return render_template("events.html", events=events)


@app.route("/metrics")
def metrics():
    return Response("hr_app_status 1\n", mimetype="text/plain")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
