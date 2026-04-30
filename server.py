#!/usr/bin/env python3
"""
VPN Subscription Server for Render.com
- HTTP API для создания подписок
- Админ-панель для подтверждения оплаты
"""

import os, json, base64, random, string
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template_string
from github import Github, Auth
from github.GithubException import GithubException

# ========== КОНФИГУРАЦИЯ ==========
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPO_NAME = "olegmmg/olegmmg.github.io"
BRANCH = "main"

app = Flask(__name__)

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

def generate_code():
    return ''.join(random.choices(string.digits, k=6))

def generate_subscription_name():
    return ''.join(random.choices(string.ascii_letters + string.digits, k=16))

# ========== ШАБЛОНЫ И ЦЕНЫ ==========
TEMPLATES = {
    "main": {
        "name": "Основная",
        "template_path": "vpn/sub",
        "output_dir": "vpn/subs"
    },
    "test": {
        "name": "Тестовая",
        "template_path": "vpn/test",
        "output_dir": "vpn/tests"
    }
}

PRICES = {
    "main": {"7d": 0, "1m": 20, "3m": 50, "12m": 180},
    "test": {"7d": 0, "1m": 30, "3m": 75, "12m": 270}
}

DAYS_MAP = {"7d": 7, "1m": 30, "3m": 90, "12m": 365}

def create_subscription(sub_type, duration):
    """Создаёт подписку"""
    template_path = TEMPLATES[sub_type]["template_path"]
    output_dir = TEMPLATES[sub_type]["output_dir"]
    days = DAYS_MAP.get(duration, 30)
    price = PRICES.get(sub_type, {}).get(duration, 0)
    
    # Получаем шаблон
    template = get_file_content(template_path)
    if not template:
        return None, f"Шаблон {template_path} не найден"
    
    # Вычисляем дату
    expire_ts = int((datetime.now() + timedelta(days=days)).timestamp())
    expire_date = (datetime.now() + timedelta(days=days)).strftime("%d.%m.%Y")
    
    # Добавляем строку userinfo
    userinfo = f"#subscription-userinfo: upload=0; download=0; total=999999999999999999999999999999999; expire={expire_ts}\n"
    final_config = userinfo + template
    
    # Сохраняем
    filename = generate_subscription_name()
    path = f"{output_dir}/{filename}"
    
    commit_msg = f"Подписка {sub_type} на {days} дней (до {expire_date})"
    if save_file(path, final_config, commit_msg):
        url = f"https://olegmmg.github.io/{path}"
        return url, f"✅ Ссылка: {url}\n📅 Действительна до: {expire_date}"
    return None, "❌ Ошибка сохранения"

# ========== HTTP ЭНДПОИНТЫ ==========
@app.route('/')
def index():
    return '''
    <h1>🔐 VPN Subscription Bot</h1>
    <ul>
        <li><a href="/admin">📋 Админ-панель</a></li>
        <li><a href="/prices">💰 Цены</a></li>
    </ul>
    '''

@app.route('/prices')
def prices():
    return render_template_string('''
    <h1>💰 Цены на VPN</h1>
    <table border="1" cellpadding="10">
        <tr><th>Тип</th><th>7 дней</th><th>1 месяц</th><th>3 месяца</th><th>1 год</th></tr>
        <tr><td>🇷🇺 Основная</td><td>0₽</td><td>20₽</td><td>50₽</td><td>180₽</td></tr>
        <tr><td>🧪 Тестовая</td><td>0₽</td><td>30₽</td><td>75₽</td><td>270₽</td></tr>
    </table>
    <p><a href="/">← Назад</a></p>
    ''')

@app.route('/api/create', methods=['POST'])
def api_create():
    """Создаёт подписку по API"""
    data = request.json
    sub_type = data.get('type', 'main')
    duration = data.get('duration', '1m')
    
    url, msg = create_subscription(sub_type, duration)
    if url:
        return jsonify({'success': True, 'url': url, 'message': msg})
    return jsonify({'success': False, 'error': msg})

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if not repo:
        return "<h1>❌ GitHub не настроен</h1><p>Укажите GITHUB_TOKEN</p>"
    
    message = None
    html = '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>VPN Admin</title>
        <meta charset="utf-8">
        <style>
            body { font-family: Arial; margin: 20px; background: #f0f2f5; }
            .container { max-width: 1200px; margin: auto; }
            .card { background: white; border-radius: 12px; padding: 20px; margin-bottom: 20px; }
            h1 { color: #1a73e8; }
            table { width: 100%; border-collapse: collapse; }
            th, td { padding: 10px; text-align: left; border-bottom: 1px solid #ddd; }
            th { background: #1a73e8; color: white; }
            .btn { padding: 8px 16px; border: none; border-radius: 6px; cursor: pointer; }
            .btn-success { background: #28a745; color: white; }
            .btn-danger { background: #dc3545; color: white; }
            .status-pending { background: #ffc107; padding: 4px 8px; border-radius: 12px; }
            .status-completed { background: #28a745; color: white; padding: 4px 8px; border-radius: 12px; }
            form { display: inline; }
            input, select { padding: 8px; margin: 5px; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🔐 VPN Admin Panel</h1>
            
            <div class="card">
                <h2>➕ Создать подписку вручную</h2>
                <form method="POST" action="/admin/create">
                    <select name="sub_type">
                        <option value="main">Основная</option>
                        <option value="test">Тестовая</option>
                    </select>
                    <select name="duration">
                        <option value="7d">7 дней (0₽)</option>
                        <option value="1m">1 месяц</option>
                        <option value="3m">3 месяца</option>
                        <option value="12m">1 год</option>
                    </select>
                    <button type="submit" class="btn" style="background:#1a73e8;color:white">Создать</button>
                </form>
            </div>
            
            <div class="card">
                <h2>💰 Цены</h2>
                <table>
                    <tr><th>Тип</th><th>7 дней</th><th>1 месяц</th><th>3 месяца</th><th>1 год</th></tr>
                    <tr><td>Основная</td><td>0₽</td><td>20₽</td><td>50₽</td><td>180₽</td></tr>
                    <tr><td>Тестовая</td><td>0₽</td><td>30₽</td><td>75₽</td><td>270₽</td></tr>
                </table>
            </div>
            
            <div class="card">
                <h2>📋 Реквизиты для оплаты</h2>
                <p>💳 <strong>Карта:</strong> 2202 2080 1284 2135</p>
                <p>👤 <strong>Получатель:</strong> Олег Ф.</p>
                <p>📝 <strong>Комментарий:</strong> укажите код из заявки</p>
            </div>
        </div>
    </body>
    </html>
    '''
    
    if message:
        html = html.replace('</body>', f'<div style="background:#d4edda;padding:10px;margin:10px">{message}</div></body>')
    return html

@app.route('/admin/create', methods=['POST'])
def admin_create():
    sub_type = request.form.get('sub_type', 'main')
    duration = request.form.get('duration', '1m')
    url, msg = create_subscription(sub_type, duration)
    return f"<html><body><h1>{msg}</h1><a href='/admin'>← Назад</a></body></html>"

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 VPN Server запущен на порту {port}")
    print(f"📁 Админка: http://localhost:{port}/admin")
    app.run(host='0.0.0.0', port=port, debug=False)
