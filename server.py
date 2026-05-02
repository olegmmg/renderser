#!/usr/bin/env python3
"""
VPN Subscription Server for Render.com
- Регистрация и авторизация пользователей
- Создание подписок и заявок
- Автопродление при покупке (если такой же тип тарифа)
- Мгновенная активация пробной подписки (без заявки)
- Замена истекших подписок на заглушку
- Автоудаление через 7 дней после истечения
- Админ-панель с отображением статуса пробной подписки
"""

import os, json, base64, random, string, hashlib, uuid
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template_string, redirect
from flask_cors import CORS
from github import Github, Auth

# ========== КОНФИГУРАЦИЯ ==========
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPO_NAME = "olegmmg/olegmmg.github.io"
BRANCH = "main"

app = Flask(__name__)
CORS(app)

# ========== GITHUB ==========
github = None
repo = None

if GITHUB_TOKEN:
    try:
        auth = Auth.Token(GITHUB_TOKEN)
        github = Github(auth=auth)
        repo = github.get_repo(REPO_NAME)
        print("✅ GitHub подключён")
    except Exception as e:
        print(f"❌ GitHub ошибка: {e}")
else:
    print("⚠️ GITHUB_TOKEN не задан")

def get_file_content(path):
    if not repo: return None
    try:
        contents = repo.get_contents(path, ref=BRANCH)
        return base64.b64decode(contents.content).decode('utf-8')
    except:
        return None

def save_file(path, content, commit_message):
    if not repo: return False
    try:
        try:
            existing = repo.get_contents(path, ref=BRANCH)
            repo.update_file(path, commit_message, content, existing.sha, branch=BRANCH)
        except:
            repo.create_file(path, commit_message, content, branch=BRANCH)
        return True
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return False

def delete_file(path):
    if not repo: return False
    try:
        existing = repo.get_contents(path, ref=BRANCH)
        repo.delete_file(path, f"Удалён {path}", existing.sha, branch=BRANCH)
        return True
    except:
        return False

def list_files_in_dir(directory):
    if not repo: return []
    try:
        contents = repo.get_contents(directory, ref=BRANCH)
        return [c.name for c in contents if c.type == "file"]
    except:
        return []

def generate_subscription_name():
    return ''.join(random.choices(string.ascii_letters + string.digits, k=16))

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# ========== ПАРАМЕТРЫ ==========
TEMPLATES = {
    "main": {"name": "Основная", "template_path": "vpn/subN", "output_dir": "vpn/subs"},
    "test": {"name": "Тестовая", "template_path": "vpn/testN", "output_dir": "vpn/tests"}
}

PRICES = {"main": {"7d": 0, "1m": 20, "3m": 50, "12m": 180}, "test": {"7d": 0, "1m": 30, "3m": 75, "12m": 270}}
DAYS_MAP = {"7d": 7, "1m": 30, "3m": 90, "12m": 365}

# Заглушка для истекших подписок
EXPIRED_SUB_CONTENT = """#subscription-userinfo: upload=0; download=0; total=0; expire=0
ss://Y2hhY2hhMjAtaWV0Zi1wb2x5MTMwNTo2VGhEMUFnd1hjOFN0cHA3aEVvaExh@0.0.0.0:10000#Подписка истекла
ss://Y2hhY2hhMjAtaWV0Zi1wb2x5MTMwNTo2VGhEMUFnd1hjOFN0cHA3aEVvaExh@0.0.0.0:10000#Продлите на
ss://Y2hhY2hhMjAtaWV0Zi1wb2x5MTMwNTo2VGhEMUFnd1hjOFN0cHA3aEVvaExh@0.0.0.0:10000#olegmmg.github.io/vpn"""

USERS_FILE = "data/users.json"
ORDERS_DIR = "data/orders"

# ========== РАБОТА С ПОЛЬЗОВАТЕЛЯМИ ==========
def get_users():
    content = get_file_content(USERS_FILE)
    if content:
        return json.loads(content)
    return {}

def save_users(users):
    save_file(USERS_FILE, json.dumps(users, ensure_ascii=False, indent=2), "Обновление пользователей")

def get_user_by_token(token):
    users = get_users()
    for email, user in users.items():
        if user.get('token') == token:
            return email, user
    return None, None

def user_can_take_trial(email):
    """Проверяет, не использовал ли пользователь пробную подписку (любой тип)"""
    users = get_users()
    user = users.get(email)
    if not user:
        return True
    # Проверяем все подписки пользователя: любая с duration='7d' считается пробной
    for sub in user.get('subscriptions', []):
        if sub.get('duration') == '7d':
            return False
    return True

# ========== СОЗДАНИЕ / ПРОДЛЕНИЕ ПОДПИСКИ ==========
def create_subscription(sub_type, duration, user_email=None):
    """Создаёт или продлевает подписку. Если у пользователя уже есть подписка того же типа — продлевает её."""
    template_path = TEMPLATES[sub_type]["template_path"]
    output_dir = TEMPLATES[sub_type]["output_dir"]
    days = DAYS_MAP.get(duration, 30)

    template = get_file_content(template_path)
    if not template:
        return None, f"Шаблон {template_path} не найден"

    now = datetime.now()
    users = get_users() if user_email else {}
    user = users.get(user_email, {}) if user_email else {}

    # Проверяем, есть ли у пользователя активная подписка того же типа (для продления)
    existing_sub = None
    if user_email:
        for sub in user.get('subscriptions', []):
            if sub.get('type') == sub_type:
                expire_ts = sub.get('expire_ts', 0)
                expire_dt = datetime.fromtimestamp(expire_ts)
                # Если подписка активна или истекла менее 7 дней назад — продлеваем
                if expire_dt + timedelta(days=7) > now:
                    existing_sub = sub
                    break

    # Если это пробная подписка (duration='7d'), проверяем, не использована ли она
    if duration == '7d' and user_email:
        if not user_can_take_trial(user_email):
            return None, "Пробная подписка уже была использована"

    if existing_sub:
        # ===== ПРОДЛЕНИЕ СУЩЕСТВУЮЩЕЙ =====
        current_expire_ts = existing_sub['expire_ts']
        if current_expire_ts < now.timestamp():
            new_expire_dt = now + timedelta(days=days)
        else:
            new_expire_dt = datetime.fromtimestamp(current_expire_ts) + timedelta(days=days)

        new_expire_ts = int(new_expire_dt.timestamp())
        new_expire_date = new_expire_dt.strftime("%d.%m.%Y")

        userinfo = f"#subscription-userinfo: upload=0; download=0; total=999999999999999999999999999999999; expire={new_expire_ts}\n"
        final_config = userinfo + template

        path = existing_sub['url'].replace("https://olegmmg.github.io/", "")

        if save_file(path, final_config, f"Продление {sub_type} до {new_expire_date}"):
            existing_sub['expire_date'] = new_expire_date
            existing_sub['expire_ts'] = new_expire_ts
            existing_sub['duration'] = f"продлён до {new_expire_date}"
            existing_sub['updated_at'] = now.isoformat()
            save_users(users)
            url = f"https://olegmmg.github.io/{path}"
            return url, f"Продлена до {new_expire_date} (добавлено {days} дней)"

    # ===== НОВАЯ ПОДПИСКА =====
    expire_ts = int((now + timedelta(days=days)).timestamp())
    expire_date = (now + timedelta(days=days)).strftime("%d.%m.%Y")
    userinfo = f"#subscription-userinfo: upload=0; download=0; total=999999999999999999999999999999999; expire={expire_ts}\n"
    final_config = userinfo + template

    filename = generate_subscription_name()
    path = f"{output_dir}/{filename}"

    if save_file(path, final_config, f"Подписка {sub_type} до {expire_date}"):
        url = f"https://olegmmg.github.io/{path}"

        if user_email:
            if 'subscriptions' not in user:
                user['subscriptions'] = []
            user['subscriptions'].append({
                'type': sub_type,
                'duration': duration,
                'plan_name': f"{TEMPLATES[sub_type]['name']} на {days} дней",
                'expire_date': expire_date,
                'expire_ts': expire_ts,
                'url': url,
                'filename': filename,
                'created_at': now.isoformat()
            })
            # Если это пробная, помечаем использованной
            if duration == '7d':
                user['trial_used'] = True
            save_users(users)

        return url, f"Действительна до {expire_date}"
    return None, "Ошибка сохранения"

# ========== ПРОВЕРКА И ЗАМЕНА ИСТЕКШИХ ПОДПИСОК ==========
def check_expired_subscriptions():
    """Проверяет все подписки: истекшие заменяет на заглушку, через 7 дней удаляет."""
    if not repo:
        return {"error": "GitHub не подключён"}

    now = int(datetime.now().timestamp())
    results = {"replaced": [], "deleted": [], "skipped": 0}

    for sub_type in ["main", "test"]:
        output_dir = TEMPLATES[sub_type]["output_dir"]
        files = list_files_in_dir(output_dir)

        for filename in files:
            path = f"{output_dir}/{filename}"
            content = get_file_content(path)
            if not content:
                continue

            expire_ts = 0
            for line in content.split('\n'):
                if line.startswith('#subscription-userinfo:') and 'expire=' in line:
                    try:
                        expire_ts = int(line.split('expire=')[1].split(';')[0].split('\n')[0])
                    except:
                        pass
                    break

            if expire_ts == 0:
                results["skipped"] += 1
                continue

            if expire_ts > now:
                results["skipped"] += 1
                continue

            # Истекла
            delete_deadline = expire_ts + (7 * 24 * 60 * 60)

            if now >= delete_deadline:
                if delete_file(path):
                    results["deleted"].append(f"{sub_type}/{filename}")
            else:
                if "Подписка истекла" not in content:
                    stub = EXPIRED_SUB_CONTENT.replace("expire=0", f"expire={expire_ts}")
                    if save_file(path, stub, f"Подписка {filename} истекла"):
                        results["replaced"].append(f"{sub_type}/{filename}")
                else:
                    if f"expire={expire_ts}" not in content:
                        stub = EXPIRED_SUB_CONTENT.replace("expire=0", f"expire={expire_ts}")
                        save_file(path, stub, f"Обновление заглушки {filename}")
                    results["skipped"] += 1

    return results

# ========== СИНХРОНИЗАЦИЯ ==========
def sync_all_subscriptions():
    results = {"main": 0, "test": 0}
    for sub_type in ["main", "test"]:
        template = get_file_content(TEMPLATES[sub_type]["template_path"])
        if not template: continue

        files = list_files_in_dir(TEMPLATES[sub_type]["output_dir"])
        for filename in files:
            path = f"{TEMPLATES[sub_type]['output_dir']}/{filename}"
            try:
                existing_file = repo.get_contents(path, ref=BRANCH)
                old_content = base64.b64decode(existing_file.content).decode('utf-8')

                if "Подписка истекла" in old_content:
                    continue

                old_userinfo = ""
                for line in old_content.split('\n'):
                    if line.startswith('#subscription-userinfo:'):
                        old_userinfo = line
                        break

                new_content = (old_userinfo + '\n' + template) if old_userinfo else template
                repo.update_file(path, f"Синхронизация", new_content, existing_file.sha, branch=BRANCH)
                results[sub_type] += 1
            except:
                pass
    return results

def get_all_subscriptions():
    subs = []
    for sub_type in ["main", "test"]:
        output_dir = TEMPLATES[sub_type]["output_dir"]
        files = list_files_in_dir(output_dir)
        for filename in files:
            path = f"{output_dir}/{filename}"
            content = get_file_content(path)
            expire_date = "не указана"
            is_expired = False
            is_stub = False

            if content:
                if "Подписка истекла" in content:
                    is_stub = True
                for line in content.split('\n'):
                    if 'expire=' in line:
                        try:
                            ts = int(line.split('expire=')[1].split(';')[0])
                            expire_date = datetime.fromtimestamp(ts).strftime("%d.%m.%Y %H:%M")
                            if ts < int(datetime.now().timestamp()):
                                is_expired = True
                        except: pass
                        break

            subs.append({
                "type": sub_type,
                "type_name": TEMPLATES[sub_type]["name"],
                "filename": filename,
                "path": path,
                "url": f"https://olegmmg.github.io/{path}",
                "expire_date": expire_date,
                "expired": is_expired,
                "is_stub": is_stub
            })
    return subs

# ========== API ЭНДПОИНТЫ ==========

@app.route('/')
def index():
    return redirect("https://olegmmg.github.io/")

@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')

    if not email or not password or len(password) < 6:
        return jsonify({'success': False, 'error': 'Email и пароль (мин. 6 символов)'})

    users = get_users()
    if email in users:
        return jsonify({'success': False, 'error': 'Email уже зарегистрирован'})

    token = str(uuid.uuid4())
    users[email] = {
        'email': email,
        'password': hash_password(password),
        'token': token,
        'subscriptions': [],
        'orders': [],
        'trial_used': False,
        'created_at': datetime.now().isoformat()
    }
    save_users(users)
    return jsonify({'success': True, 'token': token, 'user': {'email': email}})

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')

    users = get_users()
    user = users.get(email)

    if not user or user.get('password') != hash_password(password):
        return jsonify({'success': False, 'error': 'Неверный email или пароль'})

    new_token = str(uuid.uuid4())
    user['token'] = new_token
    save_users(users)
    return jsonify({'success': True, 'token': new_token, 'user': {'email': email}})

@app.route('/api/verify', methods=['POST'])
def verify():
    data = request.json
    token = data.get('token')
    users = get_users()
    for email, user in users.items():
        if user.get('token') == token:
            return jsonify({'valid': True, 'user': {'email': email}})
    return jsonify({'valid': False})

@app.route('/api/my-subscriptions', methods=['GET'])
def my_subscriptions():
    auth = request.headers.get('Authorization', '')
    token = auth.replace('Bearer ', '')
    email, user = get_user_by_token(token)
    if not user:
        return jsonify({'subscriptions': []})

    subs = user.get('subscriptions', [])
    now_ts = int(datetime.now().timestamp())
    for sub in subs:
        if sub.get('expire_ts', 0) < now_ts:
            sub['status'] = 'expired'
            if sub.get('expire_ts', 0) + (7 * 24 * 60 * 60) < now_ts:
                sub['status'] = 'deleted'
        else:
            sub['status'] = 'active'

    subs.sort(key=lambda x: x.get('expire_ts', 0), reverse=True)
    return jsonify({'subscriptions': subs})

@app.route('/api/can-take-trial', methods=['GET'])
def can_take_trial():
    auth = request.headers.get('Authorization', '')
    token = auth.replace('Bearer ', '')
    email, user = get_user_by_token(token)
    if not user:
        return jsonify({'can_take': False})
    can = user_can_take_trial(email)
    return jsonify({'can_take': can})

@app.route('/api/activate-trial', methods=['POST'])
def activate_trial():
    auth = request.headers.get('Authorization', '')
    token = auth.replace('Bearer ', '')
    email, user = get_user_by_token(token)
    if not user:
        return jsonify({'success': False, 'error': 'Не авторизован'})

    if not user_can_take_trial(email):
        return jsonify({'success': False, 'error': 'Пробная подписка уже использована'})

    data = request.json
    sub_type = data.get('type', 'main')
    if sub_type not in ['main', 'test']:
        return jsonify({'success': False, 'error': 'Неверный тип подписки'})

    url, msg = create_subscription(sub_type, '7d', email)
    if url:
        # Обновляем trial_used явно (на случай если create_subscription не сохранил)
        users = get_users()
        if email in users:
            users[email]['trial_used'] = True
            save_users(users)
        return jsonify({'success': True, 'url': url, 'message': msg})
    else:
        return jsonify({'success': False, 'error': msg})

@app.route('/api/create-order', methods=['POST'])
def create_order():
    auth = request.headers.get('Authorization', '')
    token = auth.replace('Bearer ', '')
    email, user = get_user_by_token(token)
    if not user:
        return jsonify({'success': False, 'error': 'Не авторизован'})

    data = request.json
    code = data.get('code')
    if not code:
        return jsonify({'success': False, 'error': 'Нет кода'})

    order = {
        'code': code,
        'user_email': email,
        'type': data.get('type'),
        'duration': data.get('duration'),
        'days': data.get('days'),
        'price': data.get('price'),
        'plan_name': data.get('plan_name'),
        'timestamp': datetime.now().isoformat(),
        'status': 'pending'
    }

    if save_file(f"{ORDERS_DIR}/{code}.json", json.dumps(order, ensure_ascii=False, indent=2), f"Заявка #{code}"):
        if 'orders' not in user:
            user['orders'] = []
        user['orders'].append({'code': code, 'status': 'pending', 'created_at': order['timestamp']})
        save_users(get_users())
        return jsonify({'success': True, 'code': code})
    return jsonify({'success': False, 'error': 'Ошибка сохранения'})

@app.route('/api/create', methods=['POST'])
def api_create():
    data = request.json
    sub_type = data.get('type', 'main')
    duration = data.get('duration', '1m')
    user_email = data.get('user_email')
    url, msg = create_subscription(sub_type, duration, user_email)
    if url:
        return jsonify({'success': True, 'url': url, 'message': msg})
    return jsonify({'success': False, 'error': msg})

@app.route('/api/check-expired', methods=['GET', 'POST'])
def api_check_expired():
    results = check_expired_subscriptions()
    return jsonify({'success': True, **results})

# ========== АДМИН-ПАНЕЛЬ ==========

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if not repo:
        return "<h1>❌ GitHub не настроен</h1><p>Укажите GITHUB_TOKEN</p>"

    all_subs = get_all_subscriptions()
    main_subs = [s for s in all_subs if s['type'] == 'main']
    test_subs = [s for s in all_subs if s['type'] == 'test']

    orders = []
    try:
        contents = repo.get_contents(ORDERS_DIR, ref=BRANCH)
        for c in contents:
            if c.name.endswith('.json'):
                data = json.loads(base64.b64decode(c.content).decode())
                orders.append(data)
        orders.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    except:
        pass

    users = get_users()
    users_list = []
    for e, u in users.items():
        users_list.append({
            'email': e,
            'subscriptions_count': len(u.get('subscriptions', [])),
            'created_at': u.get('created_at', ''),
            'trial_used': u.get('trial_used', False) or any(s.get('duration') == '7d' for s in u.get('subscriptions', []))
        })
    users_list.sort(key=lambda x: x['created_at'], reverse=True)

    message = None
    message_type = None

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'create':
            sub_type = request.form.get('subscription_type')
            duration = request.form.get('duration')
            user_email = request.form.get('user_email')
            url, msg = create_subscription(sub_type, duration, user_email if user_email else None)
            if url:
                message = f"✅ Подписка создана!<br>🔗 {url}<br>📅 {msg}"
                if user_email:
                    message += f"<br>👤 Пользователь: {user_email}"
                message_type = 'success'
            else:
                message = f"❌ {msg}"
                message_type = 'error'

        elif action == 'delete':
            delete_type = request.form.get('delete_type')
            filename = request.form.get('delete_file')
            path = f"{TEMPLATES[delete_type]['output_dir']}/{filename}"
            if delete_file(path):
                message = "✅ Подписка удалена"
                message_type = 'success'
            else:
                message = "❌ Ошибка удаления"
                message_type = 'error'

        elif action == 'sync':
            results = sync_all_subscriptions()
            message = f"🔄 Синхронизация завершена!<br>📁 Основные: {results['main']}, Тестовые: {results['test']}"
            message_type = 'warning'

        elif action == 'check_expired':
            results = check_expired_subscriptions()
            msg_parts = []
            if results.get('replaced'):
                msg_parts.append(f"🔄 Заменены на заглушку ({len(results['replaced'])}):<br>" + "<br>".join(results['replaced']))
            if results.get('deleted'):
                msg_parts.append(f"🗑️ Удалены ({len(results['deleted'])}):<br>" + "<br>".join(results['deleted']))
            if not msg_parts:
                msg_parts.append(f"✅ Всё актуально (проверено {results.get('skipped', 0)} подписок)")
            message = "<br><br>".join(msg_parts)
            message_type = 'success' if not results.get('error') else 'error'

        elif action == 'confirm_order':
            code = request.form.get('order_code')
            path = f"{ORDERS_DIR}/{code}.json"
            content = get_file_content(path)
            if content:
                order = json.loads(content)
                user_email = order.get('user_email')
                sub_type = order.get('type', 'main')
                duration = order.get('duration', '1m')

                # Пробная подписка уже обрабатывается на фронте отдельно, но оставим проверку
                url, msg = create_subscription(sub_type, duration, user_email)
                if url:
                    delete_file(path)
                    users_local = get_users()
                    if user_email in users_local:
                        for o in users_local[user_email].get('orders', []):
                            if o.get('code') == code:
                                o['status'] = 'completed'
                                o['subscription_url'] = url
                                break
                        save_users(users_local)
                    message = f"✅ Заявка {code} подтверждена!<br>📅 {msg}"
                    message_type = 'success'
                else:
                    message = f"❌ Ошибка: {msg}"
                    message_type = 'error'
                    delete_file(path)
            else:
                message = "❌ Заявка не найдена"
                message_type = 'error'

        elif action == 'delete_order':
            code = request.form.get('order_code')
            path = f"{ORDERS_DIR}/{code}.json"
            if delete_file(path):
                message = f"✅ Заявка {code} удалена (отклонена)"
                message_type = 'success'
            else:
                message = "❌ Ошибка удаления"
                message_type = 'error'

        return redirect('/admin')

    return render_template_string(ADMIN_TEMPLATE,
                                  main_subs=main_subs,
                                  test_subs=test_subs,
                                  orders=orders,
                                  users=users_list,
                                  message=message,
                                  message_type=message_type)

# ========== ТЁМНАЯ АДМИН-ПАНЕЛЬ ==========
ADMIN_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>VPN Admin Panel</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0a0e1a; padding: 20px; color: #e2e8f0; }
        .container { max-width: 1400px; margin: 0 auto; }
        h1 { color: #60a5fa; margin-bottom: 20px; }
        h2 { margin: 0 0 15px 0; color: #94a3b8; border-bottom: 2px solid #3b82f6; display: inline-block; padding-bottom: 5px; }
        .card { background: #111827; border-radius: 16px; padding: 20px; margin-bottom: 20px; border: 1px solid #1f2937; }
        .tabs { display: flex; gap: 5px; margin-bottom: 20px; flex-wrap: wrap; }
        .tab-btn { padding: 10px 20px; border: none; background: #1f2937; border-radius: 10px; cursor: pointer; color: #94a3b8; }
        .tab-btn.active { background: #3b82f6; color: white; }
        .tab-content { display: none; }
        .tab-content.active { display: block; }
        .btn { padding: 8px 16px; margin: 5px; border: none; border-radius: 8px; cursor: pointer; font-size: 13px; }
        .btn-primary { background: #3b82f6; color: white; }
        .btn-success { background: #22c55e; color: white; }
        .btn-danger { background: #ef4444; color: white; }
        .btn-warning { background: #f59e0b; color: #1a1a2e; }
        .btn-purple { background: #8b5cf6; color: white; }
        table { width: 100%; border-collapse: collapse; margin-top: 15px; }
        th, td { padding: 10px; text-align: left; border-bottom: 1px solid #1f2937; }
        th { background: #0f1622; color: #60a5fa; }
        tr:hover { background: #1a2332; }
        select, input { background: #1f2937; color: #e2e8f0; border: 1px solid #374151; padding: 8px; border-radius: 6px; }
        .status-pending { background: #f59e0b; color: #000; padding: 2px 8px; border-radius: 20px; font-size: 11px; }
        .status-completed { background: #22c55e; color: #000; padding: 2px 8px; border-radius: 20px; font-size: 11px; }
        .expired { background: #ef4444; color: white; padding: 2px 8px; border-radius: 20px; font-size: 11px; }
        .stub { background: #8b5cf6; color: white; padding: 2px 8px; border-radius: 20px; font-size: 11px; }
        .active-sub { background: #22c55e; color: #000; padding: 2px 8px; border-radius: 20px; font-size: 11px; }
        .success { background: #065f46; color: #d1fae5; padding: 12px; border-radius: 12px; margin-bottom: 15px; }
        .error { background: #991b1b; color: #fecaca; padding: 12px; border-radius: 12px; margin-bottom: 15px; }
        .warning { background: #92400e; color: #fef3c7; padding: 12px; border-radius: 12px; margin-bottom: 15px; }
        .row { display: flex; gap: 20px; flex-wrap: wrap; }
        .col { flex: 1; min-width: 300px; }
        code { background: #1f2937; padding: 2px 6px; border-radius: 4px; font-size: 11px; word-break: break-all; }
        a { color: #60a5fa; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🔐 VPN Admin Panel</h1>
        
        {% if message %}
        <div class="{{ message_type }}">{{ message | safe }}</div>
        {% endif %}
        
        <div class="tabs">
            <button class="tab-btn active" onclick="showTab('orders')">📋 Заявки</button>
            <button class="tab-btn" onclick="showTab('subscriptions')">🔑 Подписки</button>
            <button class="tab-btn" onclick="showTab('users')">👥 Пользователи</button>
            <button class="tab-btn" onclick="showTab('create')">➕ Создать</button>
            <button class="tab-btn" onclick="showTab('tools')">🛠️ Инструменты</button>
        </div>
        
        <!-- Заявки -->
        <div id="tab-orders" class="tab-content active">
            <div class="card">
                <h2>📋 Заявки на оплату</h2>
                <table>
                    <thead>
                        <tr><th>Код</th><th>Пользователь</th><th>Тариф</th><th>Сумма</th><th>Дата</th><th>Статус</th><th>Действие</th></tr>
                    </thead>
                    <tbody>
                        {% for order in orders %}
                        <tr>
                            <td><strong>{{ order.code }}</strong></td>
                            <td>{{ order.user_email }}</td>
                            <td>{{ order.plan_name }}</td>
                            <td>{{ order.price }}₽</td>
                            <td>{{ order.timestamp[:16] }}</td>
                            <td>{% if order.status == 'pending' %}<span class="status-pending">⏳ Ожидает</span>{% else %}<span class="status-completed">✅ Выполнена</span>{% endif %}</td>
                            <td>
                                {% if order.status == 'pending' %}
                                <form method="POST" style="display:inline;">
                                    <input type="hidden" name="action" value="confirm_order">
                                    <input type="hidden" name="order_code" value="{{ order.code }}">
                                    <button type="submit" class="btn-success" style="padding:4px 12px;">✅</button>
                                </form>
                                <form method="POST" style="display:inline;">
                                    <input type="hidden" name="action" value="delete_order">
                                    <input type="hidden" name="order_code" value="{{ order.code }}">
                                    <button type="submit" class="btn-danger" style="padding:4px 12px;">🗑️</button>
                                </form>
                                {% endif %}
                            </td>
                        </tr>
                        {% else %}
                        <tr><td colspan="7">Нет заявок</td></tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
        
        <!-- Подписки -->
        <div id="tab-subscriptions" class="tab-content">
            <div class="card">
                <h2>📁 Основные подписки (vpn/subs)</h2>
                <table>
                    <thead>
                        <tr><th>Файл</th><th>Действительна до</th><th>Статус</th><th>Ссылка</th><th></th></tr>
                    </thead>
                    <tbody>
                        {% for sub in main_subs %}
                        <tr>
                            <td><code>{{ sub.filename }}</code></td>
                            <td>{{ sub.expire_date }}</td>
                            <td>
                                {% if sub.is_stub %}<span class="stub">🔒 Заглушка</span>
                                {% elif sub.expired %}<span class="expired">❌ Истекла</span>
                                {% else %}<span class="active-sub">✅ Активна</span>
                                {% endif %}
                            </td>
                            <td><a href="{{ sub.url }}" target="_blank"><code style="font-size:9px;">{{ sub.filename }}</code></a></td>
                            <td>
                                <form method="POST">
                                    <input type="hidden" name="action" value="delete">
                                    <input type="hidden" name="delete_type" value="main">
                                    <input type="hidden" name="delete_file" value="{{ sub.filename }}">
                                    <button type="submit" class="btn-danger" style="padding:4px 10px;">🗑️</button>
                                </form>
                            </td>
                        </tr>
                        {% else %}
                        <tr><td colspan="5">Нет подписок</td></tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
            <div class="card">
                <h2>🧪 Тестовые подписки (vpn/tests)</h2>
                <table>
                    <thead>
                        <tr><th>Файл</th><th>Действительна до</th><th>Статус</th><th>Ссылка</th><th></th></tr>
                    </thead>
                    <tbody>
                        {% for sub in test_subs %}
                        <tr>
                            <td><code>{{ sub.filename }}</code></td>
                            <td>{{ sub.expire_date }}</td>
                            <td>
                                {% if sub.is_stub %}<span class="stub">🔒 Заглушка</span>
                                {% elif sub.expired %}<span class="expired">❌ Истекла</span>
                                {% else %}<span class="active-sub">✅ Активна</span>
                                {% endif %}
                            </td>
                            <td><a href="{{ sub.url }}" target="_blank"><code style="font-size:9px;">{{ sub.filename }}</code></a></td>
                            <td>
                                <form method="POST">
                                    <input type="hidden" name="action" value="delete">
                                    <input type="hidden" name="delete_type" value="test">
                                    <input type="hidden" name="delete_file" value="{{ sub.filename }}">
                                    <button type="submit" class="btn-danger" style="padding:4px 10px;">🗑️</button>
                                </form>
                            </td>
                        </tr>
                        {% else %}
                        <tr><td colspan="5">Нет подписок</td></tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
        
        <!-- Пользователи -->
        <div id="tab-users" class="tab-content">
            <div class="card">
                <h2>👥 Зарегистрированные пользователи</h2>
                <table>
                    <thead>
                        <tr><th>Email</th><th>Подписок</th><th>Дата регистрации</th></tr>
                    </thead>
                    <tbody>
                        {% for user in users %}
                        <tr>
                            <td>{{ user.email }}</td>
                            <td>{{ user.subscriptions_count }}</td>
                            <td>{{ user.created_at[:16] }}</td>
                        </tr>
                        {% else %}
                        <tr><td colspan="3">Нет пользователей</td></tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
            <div class="card">
                <h2>💰 Реквизиты для оплаты</h2>
                <p>💳 Карта: <strong>2202 2080 1284 2135</strong></p>
                <p>👤 Получатель: <strong>Олег Ф.</strong></p>
                <p>📝 Комментарий: <strong>код из заявки (6 цифр)</strong></p>
            </div>
        </div>
        
        <!-- Создание подписки -->
        <div id="tab-create" class="tab-content">
            <div class="card">
                <h2>➕ Создать подписку вручную</h2>
                <form method="POST">
                    <div style="margin-bottom:10px;">
                        <select name="subscription_type">
                            <option value="main">🇷🇺 Основная</option>
                            <option value="test">🧪 Тестовая</option>
                        </select>
                    </div>
                    <div style="margin-bottom:10px;">
                        <select name="duration">
                            <option value="7d">Пробная (7 дней)</option>
                            <option value="1m">1 месяц</option>
                            <option value="3m">3 месяца</option>
                            <option value="12m">1 год</option>
                        </select>
                    </div>
                    <div style="margin-bottom:10px;">
                        <input type="text" name="user_email" placeholder="Email пользователя (опционально)">
                    </div>
                    <button type="submit" name="action" value="create" class="btn btn-primary">Создать / Продлить подписку</button>
                </form>
            </div>
        </div>
        
        <!-- Инструменты -->
        <div id="tab-tools" class="tab-content">
            <div class="card">
                <h2>🔄 Синхронизация подписок с шаблонами</h2>
                <p>Обновляет все АКТИВНЫЕ подписки по текущим шаблонам (даты окончания сохраняются). Истекшие (заглушки) пропускаются.</p>
                <form method="POST">
                    <button type="submit" name="action" value="sync" class="btn btn-warning">🔄 Синхронизировать все подписки</button>
                </form>
            </div>
            <div class="card">
                <h2>🔍 Проверка истекших подписок</h2>
                <p>Истекшие заменяются на заглушку. Через 7 дней после истечения — удаляются полностью.</p>
                <form method="POST">
                    <button type="submit" name="action" value="check_expired" class="btn btn-purple">🔍 Проверить истекшие</button>
                </form>
            </div>
        </div>
    </div>
    
    <script>
        function showTab(tab) {
            document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
            document.getElementById('tab-' + tab).classList.add('active');
            event.target.classList.add('active');
        }
    </script>
</body>
</html>
'''

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 VPN Server запущен на порту {port}")
    print(f"📁 Админка: http://localhost:{port}/admin")
    app.run(host='0.0.0.0', port=port, debug=False)
