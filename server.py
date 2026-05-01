#!/usr/bin/env python3
"""
VPN Subscription Server for Render.com
- Регистрация и авторизация пользователей
- Создание подписок и заявок
- Админ-панель для управления
- АВТОМАТИЧЕСКАЯ ЗАМЕНА ИСТЕКШИХ ПОДПИСОК НА ЗАГЛУШКУ
"""

import os, json, base64, random, string, hashlib, uuid
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template_string, redirect
from flask_cors import CORS
from github import Github, Auth
from github.GithubException import GithubException

# ========== КОНФИГУРАЦИЯ ==========
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPO_NAME = "olegmmg/olegmmg.github.io"
BRANCH = "main"

app = Flask(__name__)
CORS(app)

# ========== ЗАГЛУШКА ДЛЯ ИСТЕКШИХ ПОДПИСОК ==========
EXPIRED_CONFIG = """#profile-title: VPN - @Olegmmg
#profile-update-interval: 2
#subscription-userinfo: upload=0; download=0; total=999999999999999999999999999999999; expire=0

ss://Y2hhY2hhMjAtaWV0Zi1wb2x5MTMwNTo2VGhEMUFnd1hjOFN0cHA3aEVvaExh@0.0.0.0:10000#Подписка истекла
ss://Y2hhY2hhMjAtaWV0Zi1wb2x5MTMwNTo2VGhEMUFnd1hjOFN0cHA3aEVvaExh@0.0.0.0:10000#Продлите на сайте
ss://Y2hhY2hhMjAtaWV0Zi1wb2x5MTMwNTo2VGhEMUFnd1hjOFN0cHA3aEVvaExh@0.0.0.0:10000#olegmmg.github.io/vpn
"""

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
    "main": {"name": "Основная", "template_path": "vpn/sub", "output_dir": "vpn/subs"},
    "test": {"name": "Тестовая", "template_path": "vpn/test", "output_dir": "vpn/tests"}
}

PRICES = {"main": {"7d": 0, "1m": 20, "3m": 50, "12m": 180}, "test": {"7d": 0, "1m": 30, "3m": 75, "12m": 270}}
DAYS_MAP = {"7d": 7, "1m": 30, "3m": 90, "12m": 365}

# Файлы для хранения данных
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

def has_trial_used(user):
    """Проверяет, использовал ли пользователь пробную подписку"""
    for sub in user.get('subscriptions', []):
        if sub.get('duration') == '7d':
            return True
    return False

# ========== ПРОВЕРКА И ЗАМЕНА ИСТЕКШИХ ПОДПИСОК ==========
def check_and_replace_expired():
    """Проверяет все подписки и заменяет истекшие на заглушку"""
    expired_count = 0
    now_ts = int(datetime.now().timestamp())
    
    for sub_type in ["main", "test"]:
        output_dir = TEMPLATES[sub_type]["output_dir"]
        files = list_files_in_dir(output_dir)
        
        for filename in files:
            path = f"{output_dir}/{filename}"
            content = get_file_content(path)
            
            if not content:
                continue
            
            # Извлекаем expire timestamp
            expire_ts = None
            for line in content.split('\n'):
                if 'expire=' in line:
                    try:
                        expire_ts = int(line.split('expire=')[1].split(';')[0])
                        break
                    except:
                        pass
            
            # Если срок истёк или expire=0, заменяем на заглушку
            if expire_ts is None or expire_ts <= now_ts:
                # Проверяем, не заглушка ли уже
                if "Подписка истекла" in content:
                    continue
                
                # Заменяем на заглушку
                try:
                    existing = repo.get_contents(path, ref=BRANCH)
                    repo.update_file(path, "Подписка истекла - замена на заглушку", 
                                   EXPIRED_CONFIG, existing.sha, branch=BRANCH)
                    expired_count += 1
                    print(f"⏰ Заменена истекшая подписка: {filename}")
                except Exception as e:
                    print(f"❌ Ошибка замены {filename}: {e}")
    
    return expired_count

# ========== СОЗДАНИЕ ПОДПИСКИ ==========
def create_subscription(sub_type, duration, user_email=None):
    template_path = TEMPLATES[sub_type]["template_path"]
    output_dir = TEMPLATES[sub_type]["output_dir"]
    days = DAYS_MAP.get(duration, 30)
    
    template = get_file_content(template_path)
    if not template:
        return None, f"Шаблон {template_path} не найден"
    
    expire_ts = int((datetime.now() + timedelta(days=days)).timestamp())
    expire_date = (datetime.now() + timedelta(days=days)).strftime("%d.%m.%Y")
    userinfo = f"#subscription-userinfo: upload=0; download=0; total=999999999999999999999999999999999; expire={expire_ts}\n"
    final_config = userinfo + template
    
    filename = generate_subscription_name()
    path = f"{output_dir}/{filename}"
    
    if save_file(path, final_config, f"Подписка {sub_type} до {expire_date}"):
        url = f"https://olegmmg.github.io/{path}"
        
        # Привязываем подписку к пользователю
        if user_email:
            users = get_users()
            if user_email in users:
                if 'subscriptions' not in users[user_email]:
                    users[user_email]['subscriptions'] = []
                # Удаляем старые истекшие подписки пользователя
                users[user_email]['subscriptions'] = [
                    sub for sub in users[user_email]['subscriptions'] 
                    if sub.get('expire_ts', 0) > int(datetime.now().timestamp())
                ]
                users[user_email]['subscriptions'].append({
                    'type': sub_type,
                    'duration': duration,
                    'plan_name': f"{TEMPLATES[sub_type]['name']} на {days} дней",
                    'expire_date': expire_date,
                    'expire_ts': expire_ts,
                    'url': url,
                    'created_at': datetime.now().isoformat()
                })
                save_users(users)
        
        return url, f"Действительна до {expire_date}"
    return None, "Ошибка сохранения"

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
                
                # Пропускаем заглушки
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
            if content:
                for line in content.split('\n'):
                    if 'expire=' in line:
                        try:
                            ts = int(line.split('expire=')[1].split(';')[0])
                            expire_date = datetime.fromtimestamp(ts).strftime("%d.%m.%Y")
                            is_expired = ts <= int(datetime.now().timestamp())
                        except: pass
                        break
            subs.append({
                "type": sub_type,
                "type_name": TEMPLATES[sub_type]["name"],
                "filename": filename,
                "path": path,
                "url": f"https://olegmmg.github.io/{path}",
                "expire_date": expire_date,
                "is_expired": is_expired
            })
    return subs

# ========== API ЭНДПОИНТЫ ==========

@app.route('/')
def index():
    return redirect("https://olegmmg.github.io/")

# Регистрация
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
        'created_at': datetime.now().isoformat()
    }
    save_users(users)
    
    return jsonify({'success': True, 'token': token, 'user': {'email': email}})

# Вход
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

# Проверка токена
@app.route('/api/verify', methods=['POST'])
def verify():
    data = request.json
    token = data.get('token')
    
    users = get_users()
    for email, user in users.items():
        if user.get('token') == token:
            return jsonify({'valid': True, 'user': {'email': email}})
    return jsonify({'valid': False})

# Можно ли взять пробную подписку
@app.route('/api/can-take-trial', methods=['GET'])
def can_take_trial():
    auth = request.headers.get('Authorization', '')
    token = auth.replace('Bearer ', '')
    
    email, user = get_user_by_token(token)
    if not user:
        return jsonify({'can_take': False, 'error': 'Не авторизован'})
    
    return jsonify({'can_take': not has_trial_used(user)})

# Мои подписки
@app.route('/api/my-subscriptions', methods=['GET'])
def my_subscriptions():
    auth = request.headers.get('Authorization', '')
    token = auth.replace('Bearer ', '')
    
    email, user = get_user_by_token(token)
    if not user:
        return jsonify({'subscriptions': []})
    
    subs = user.get('subscriptions', [])
    subs.sort(key=lambda x: x.get('expire_ts', 0), reverse=True)
    
    return jsonify({'subscriptions': subs})

# Создание заявки на оплату
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
    
    duration = data.get('duration')
    if duration == '7d' and has_trial_used(user):
        return jsonify({'success': False, 'error': 'Пробная подписка доступна только 1 раз'})
    
    order = {
        'code': code,
        'user_email': email,
        'type': data.get('type'),
        'duration': duration,
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

# Прямое создание подписки (для админа)
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

# ========== АДМИН-ПАНЕЛЬ ==========

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if not repo:
        return "<h1>❌ GitHub не настроен</h1><p>Укажите GITHUB_TOKEN</p>"
    
    # Проверяем и заменяем истекшие подписки ПРИ КАЖДОМ ЗАПРОСЕ к админке
    expired_replaced = check_and_replace_expired()
    
    main_subs = []
    test_subs = []
    for sub in get_all_subscriptions():
        if sub['type'] == 'main':
            main_subs.append(sub)
        else:
            test_subs.append(sub)
    
    # Получаем заявки
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
    
    # Получаем пользователей
    users = get_users()
    users_list = []
    for e, u in users.items():
        users_list.append({
            'email': e,
            'subscriptions_count': len(u.get('subscriptions', [])),
            'has_trial': has_trial_used(u),
            'created_at': u.get('created_at', '')
        })
    users_list.sort(key=lambda x: x['created_at'], reverse=True)
    
    message = None
    message_type = None
    
    if expired_replaced > 0:
        message = f"⏰ Автоматически заменено {expired_replaced} истекших подписок на заглушку"
        message_type = 'warning'
    
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
        
        elif action == 'expire_check':
            expired = check_and_replace_expired()
            message = f"⏰ Проверка завершена! Заменено истекших подписок: {expired}"
            message_type = 'warning'
        
        elif action == 'confirm_order':
            code = request.form.get('order_code')
            path = f"{ORDERS_DIR}/{code}.json"
            content = get_file_content(path)
            if content:
                order = json.loads(content)
                user_email = order.get('user_email')
                sub_type = order.get('type', 'main')
                duration = order.get('duration', '1m')
                is_trial = (duration == '7d')
                
                if is_trial and user_email:
                    users_check = get_users()
                    user_check = users_check.get(user_email)
                    if user_check and has_trial_used(user_check):
                        delete_file(path)
                        message = f"❌ Пользователь уже использовал пробную подписку. Заявка {code} удалена."
                        message_type = 'error'
                        return render_template_string(ADMIN_TEMPLATE, 
                                      main_subs=main_subs, test_subs=test_subs,
                                      orders=orders, users=users_list,
                                      message=message, message_type=message_type)
                
                url, msg = create_subscription(sub_type, duration, user_email)
                delete_file(path)
                
                if url:
                    users_local = get_users()
                    if user_email in users_local:
                        for o in users_local[user_email].get('orders', []):
                            if o.get('code') == code:
                                o['status'] = 'completed'
                                o['subscription_url'] = url
                                break
                        save_users(users_local)
                    message = f"✅ Заявка {code} подтверждена! Подписка создана."
                    message_type = 'success'
                else:
                    message = f"❌ Ошибка: {msg}. Заявка {code} удалена."
                    message_type = 'error'
            else:
                message = "❌ Заявка не найдена"
                message_type = 'error'
        
        elif action == 'delete_order':
            code = request.form.get('order_code')
            path = f"{ORDERS_DIR}/{code}.json"
            if delete_file(path):
                message = f"✅ Заявка {code} удалена"
                message_type = 'success'
            else:
                message = "❌ Ошибка удаления"
                message_type = 'error'
    
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
        table { width: 100%; border-collapse: collapse; margin-top: 15px; }
        th, td { padding: 10px; text-align: left; border-bottom: 1px solid #1f2937; }
        th { background: #0f1622; color: #60a5fa; }
        tr:hover { background: #1a2332; }
        select, input { background: #1f2937; color: #e2e8f0; border: 1px solid #374151; padding: 8px; border-radius: 6px; }
        .status-pending { background: #f59e0b; padding: 2px 8px; border-radius: 20px; font-size: 11px; display: inline-block; }
        .status-completed { background: #22c55e; padding: 2px 8px; border-radius: 20px; font-size: 11px; display: inline-block; }
        .expired-badge { background: #ef4444; padding: 2px 8px; border-radius: 20px; font-size: 10px; margin-left: 8px; }
        .success { background: #065f46; color: #d1fae5; padding: 12px; border-radius: 12px; margin-bottom: 15px; }
        .error { background: #991b1b; color: #fecaca; padding: 12px; border-radius: 12px; margin-bottom: 15px; }
        .warning { background: #92400e; color: #fef3c7; padding: 12px; border-radius: 12px; margin-bottom: 15px; }
        .row { display: flex; gap: 20px; flex-wrap: wrap; }
        .col { flex: 1; min-width: 300px; }
        code { background: #1f2937; padding: 2px 6px; border-radius: 4px; font-size: 11px; }
        .trial-badge { background: #8b5cf6; padding: 2px 8px; border-radius: 20px; font-size: 10px; margin-left: 5px; }
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
            <button class="tab-btn" onclick="showTab('sync')">🔄 Синхронизация</button>
        </div>
        
        <!-- Заявки -->
        <div id="tab-orders" class="tab-content active">
            <div class="card">
                <h2>📋 Заявки на оплату</h2>
                <table>
                    <thead><tr><th>Код</th><th>Пользователь</th><th>Тариф</th><th>Сумма</th><th>Дата</th><th>Статус</th><th>Действие</th></tr></thead>
                    <tbody>
                        {% for order in orders %}
                        <tr>
                            <td><strong>{{ order.code }}</strong>{% if order.duration == '7d' %}<span class="trial-badge">пробная</span>{% endif %}</span></td>
                            <td>{{ order.user_email }}</span></td>
                            <td>{{ order.plan_name }}</span></td>
                            <td>{{ order.price }}₽</span></td>
                            <td>{{ order.timestamp[:16] }}</span></td>
                            <td><span class="status-pending">⏳ Ожидает</span></span></td>
                            <td>
                                <form method="POST" style="display:inline;">
                                    <input type="hidden" name="action" value="confirm_order">
                                    <input type="hidden" name="order_code" value="{{ order.code }}">
                                    <button type="submit" class="btn-success" style="padding:4px 12px;">✅ Подтвердить</button>
                                </form>
                                <form method="POST" style="display:inline;">
                                    <input type="hidden" name="action" value="delete_order">
                                    <input type="hidden" name="order_code" value="{{ order.code }}">
                                    <button type="submit" class="btn-danger" style="padding:4px 12px;">🗑️ Отклонить</button>
                                </form>
                            </span></td>
                        </tr>
                        {% else %}
                        <tr><td colspan="7">Нет заявок</span></td>
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
                    <thead><tr><th>Файл</th><th>Действительна до</th><th>Статус</th><th>Ссылка</th><th></th></tr></thead>
                    <tbody>
                        {% for sub in main_subs %}
                        <tr>
                            <td><code>{{ sub.filename }}</code></span></td>
                            <td>{{ sub.expire_date }}</span></td>
                            <td>{% if sub.is_expired %}<span class="expired-badge">❌ Истекла</span>{% else %}✅ Активна{% endif %}</span></td>
                            <td><code style="font-size:9px;">{{ sub.url }}</code></span></td>
                            <td>
                                <form method="POST">
                                    <input type="hidden" name="action" value="delete">
                                    <input type="hidden" name="delete_type" value="main">
                                    <input type="hidden" name="delete_file" value="{{ sub.filename }}">
                                    <button type="submit" class="btn-danger" style="padding:4px 10px;">🗑️</button>
                                </form>
                            </span></td>
                        </tr>
                        {% else %}
                        <tr><td colspan="5">Нет подписок</span></td>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
            <div class="card">
                <h2>🧪 Тестовые подписки (vpn/tests)</h2>
                <table>
                    <thead><tr><th>Файл</th><th>Действительна до</th><th>Статус</th><th>Ссылка</th><th></th></tr></thead>
                    <tbody>
                        {% for sub in test_subs %}
                        <tr>
                            <td><code>{{ sub.filename }}</code></span></td>
                            <td>{{ sub.expire_date }}</span></td>
                            <td>{% if sub.is_expired %}<span class="expired-badge">❌ Истекла</span>{% else %}✅ Активна{% endif %}</span></td>
                            <td><code style="font-size:9px;">{{ sub.url }}</code></span></td>
                            <td>
                                <form method="POST">
                                    <input type="hidden" name="action" value="delete">
                                    <input type="hidden" name="delete_type" value="test">
                                    <input type="hidden" name="delete_file" value="{{ sub.filename }}">
                                    <button type="submit" class="btn-danger" style="padding:4px 10px;">🗑️</button>
                                </form>
                            </span></td>
                        </tr>
                        {% else %}
                        <tr><td colspan="5">Нет подписок</span></td>
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
                    <thead><tr><th>Email</th><th>Подписок</th><th>Пробная</th><th>Дата регистрации</th></tr></thead>
                    <tbody>
                        {% for user in users %}
                        <tr>
                            <td>{{ user.email }}</span></td>
                            <td>{{ user.subscriptions_count }}</span></td>
                            <td>{% if user.has_trial %}✅ использована{% else %}❌ не использована{% endif %}</span></td>
                            <td>{{ user.created_at[:16] }}</span></td>
                        </tr>
                        {% else %}
                        <tr><td colspan="4">Нет пользователей</span></td>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
            <div class="card">
                <h2>💰 Реквизиты для оплаты</h2>
                <p>💳 Карта: <strong>2202 2080 1284 2135</strong></p>
                <p>👤 Получатель: <strong>Олег Ф.</strong></p>
                <p>📝 Комментарий: <strong>код из заявки (6 цифр)</strong></p>
                <p style="margin-top:10px; color:#f59e0b;">⚠️ Пробная подписка — ТОЛЬКО 1 РАЗ на пользователя!</p>
                <p style="margin-top:10px; color:#ef4444;">⏰ Истекшие подписки автоматически заменяются на заглушку</p>
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
                            <option value="7d">Пробная (7 дней) — 1 раз!</option>
                            <option value="1m">1 месяц</option>
                            <option value="3m">3 месяца</option>
                            <option value="12m">1 год</option>
                        </select>
                    </div>
                    <div style="margin-bottom:10px;">
                        <input type="text" name="user_email" placeholder="Email пользователя (опционально)">
                    </div>
                    <button type="submit" name="action" value="create" class="btn btn-primary">Создать подписку</button>
                </form>
            </div>
        </div>
        
        <!-- Синхронизация -->
        <div id="tab-sync" class="tab-content">
            <div class="card">
                <h2>🔄 Синхронизация подписок с шаблонами</h2>
                <p>Обновляет все подписки по текущим шаблонам (даты окончания сохраняются).</p>
                <form method="POST">
                    <button type="submit" name="action" value="sync" class="btn btn-warning">🔄 Синхронизировать все подписки</button>
                </form>
                <hr style="margin:15px 0;">
                <form method="POST">
                    <button type="submit" name="action" value="expire_check" class="btn btn-danger">⏰ Проверить и заменить истекшие подписки</button>
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
    print("⏰ Автоматическая проверка истекших подписок включена")
    app.run(host='0.0.0.0', port=port, debug=False)
