#!/usr/bin/env python3
"""
VPN Subscription Server for Render.com
- API для создания подписок и заявок
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
    
    template = get_file_content(template_path)
    if not template:
        return None, f"Шаблон {template_path} не найден"
    
    expire_ts = int((datetime.now() + timedelta(days=days)).timestamp())
    expire_date = (datetime.now() + timedelta(days=days)).strftime("%d.%m.%Y")
    userinfo = f"#subscription-userinfo: upload=0; download=0; total=999999999999999999999999999999999; expire={expire_ts}\n"
    final_config = userinfo + template
    
    filename = generate_subscription_name()
    path = f"{output_dir}/{filename}"
    
    commit_msg = f"Подписка {sub_type} до {expire_date}"
    if save_file(path, final_config, commit_msg):
        url = f"https://olegmmg.github.io/{path}"
        return url, f"Действительна до {expire_date}"
    return None, "Ошибка сохранения"

# ========== HTTP ЭНДПОИНТЫ ==========

# --- Главная страница сайта (редирект на GitHub Pages) ---
@app.route('/')
def index():
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <meta http-equiv="refresh" content="0;url=https://olegmmg.github.io/">
        <title>VPN от @LudskoiStpax</title>
    </head>
    <body>
        <p>Перенаправление на <a href="https://olegmmg.github.io/">olegmmg.github.io</a>...</p>
    </body>
    </html>
    '''

# --- API: создание подписки напрямую ---
@app.route('/api/create', methods=['POST'])
def api_create():
    data = request.json
    sub_type = data.get('type', 'main')
    duration = data.get('duration', '1m')
    url, msg = create_subscription(sub_type, duration)
    if url:
        return jsonify({'success': True, 'url': url, 'message': msg})
    return jsonify({'success': False, 'error': msg})

# --- API: создание заявки на оплату ---
@app.route('/api/create-order', methods=['POST'])
def create_order():
    data = request.json
    code = data.get('code')
    if not code:
        return jsonify({'success': False, 'error': 'Нет кода'})
    
    # Проверяем, нет ли уже такой заявки
    existing = get_file_content(f"orders/{code}.json")
    if existing:
        return jsonify({'success': False, 'error': 'Заявка с таким кодом уже существует'})
    
    order = {
        'code': code,
        'type': data.get('type'),
        'duration': data.get('duration'),
        'days': data.get('days'),
        'price': data.get('price'),
        'plan_name': data.get('plan_name'),
        'timestamp': datetime.now().isoformat(),
        'status': 'pending'
    }
    
    if save_file(f"orders/{code}.json", json.dumps(order, ensure_ascii=False, indent=2), f"Заявка #{code}"):
        return jsonify({'success': True, 'code': code})
    return jsonify({'success': False, 'error': 'Ошибка сохранения'})

# --- Админ-панель (просмотр заявок) ---
@app.route('/admin')
def admin():
    if not repo:
        return "<h1>❌ GitHub не настроен</h1><p>Укажите GITHUB_TOKEN</p>"
    
    try:
        contents = repo.get_contents("orders", ref=BRANCH)
        orders = []
        for c in contents:
            if c.name.endswith('.json'):
                data = json.loads(base64.b64decode(c.content).decode())
                orders.append(data)
        orders.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        
        return render_template_string(ADMIN_TEMPLATE, orders=orders)
    except Exception as e:
        return f"<h1>Нет заявок</h1><p>{e}</p>"

# --- Админ: подтверждение оплаты ---
@app.route('/admin/confirm', methods=['POST'])
def confirm_order():
    code = request.form.get('code')
    path = f"orders/{code}.json"
    
    content = get_file_content(path)
    if not content:
        return "<h1>Заявка не найдена</h1><a href='/admin'>← Назад</a>"
    
    order = json.loads(content)
    sub_type = order.get('type', 'main')
    duration = order.get('duration', '1m')
    
    url, msg = create_subscription(sub_type, duration)
    
    if url:
        order['status'] = 'completed'
        order['subscription_url'] = url
        order['completed_at'] = datetime.now().isoformat()
        save_file(path, json.dumps(order, ensure_ascii=False, indent=2), f"Заявка #{code} подтверждена")
        return f"""
        <h1>✅ Подписка активирована!</h1>
        <p>Код: {code}</p>
        <p>Тип: {order.get('plan_name')}</p>
        <p>Ссылка: <a href='{url}' target='_blank'>{url}</a></p>
        <p><a href='/admin'>← К списку заявок</a></p>
        """
    else:
        return f"<h1>❌ Ошибка создания подписки</h1><p>{msg}</p><a href='/admin'>← Назад</a>"

# --- Админ: удаление заявки ---
@app.route('/admin/delete/<code>', methods=['POST'])
def delete_order(code):
    path = f"orders/{code}.json"
    try:
        existing = repo.get_contents(path, ref=BRANCH)
        repo.delete_file(path, f"Удалена заявка #{code}", existing.sha, branch=BRANCH)
        return '', 204
    except:
        return '', 404

# --- Шаблон админки ---
ADMIN_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>VPN Admin</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f0f2f5; padding: 20px; }
        .container { max-width: 1400px; margin: 0 auto; }
        h1 { color: #1a73e8; margin-bottom: 20px; }
        .card { background: white; border-radius: 16px; padding: 20px; margin-bottom: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
        .card h2 { margin-bottom: 15px; color: #333; font-size: 1.3em; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 12px; text-align: left; border-bottom: 1px solid #e2e8f0; }
        th { background: #f8f9fa; font-weight: 600; color: #1a73e8; }
        tr:hover { background: #f8f9fa; }
        .status-pending { background: #ffc107; color: #333; padding: 4px 12px; border-radius: 20px; font-size: 12px; font-weight: bold; display: inline-block; }
        .status-completed { background: #28a745; color: white; padding: 4px 12px; border-radius: 20px; font-size: 12px; font-weight: bold; display: inline-block; }
        .btn { padding: 8px 16px; border: none; border-radius: 8px; cursor: pointer; font-size: 13px; transition: 0.2s; }
        .btn-success { background: #28a745; color: white; }
        .btn-success:hover { background: #218838; }
        .btn-danger { background: #dc3545; color: white; }
        .btn-danger:hover { background: #c82333; }
        .btn-primary { background: #1a73e8; color: white; }
        .btn-primary:hover { background: #1557b0; }
        form { display: inline; }
        .badge { background: #e2e8f0; padding: 2px 8px; border-radius: 12px; font-size: 11px; margin-left: 8px; }
        .stats { display: flex; gap: 20px; flex-wrap: wrap; margin-bottom: 20px; }
        .stat-card { background: white; border-radius: 16px; padding: 20px; flex: 1; min-width: 150px; text-align: center; }
        .stat-number { font-size: 2em; font-weight: bold; color: #1a73e8; }
        .revenue { color: #28a745; }
        @media (max-width: 768px) {
            table, thead, tbody, th, td, tr { display: block; }
            thead { display: none; }
            tr { margin-bottom: 15px; border: 1px solid #e2e8f0; border-radius: 12px; padding: 10px; }
            td { display: flex; justify-content: space-between; align-items: center; padding: 8px; border: none; }
            td:before { content: attr(data-label); font-weight: bold; margin-right: 10px; }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🔐 VPN Admin Panel</h1>
        
        <div class="stats">
            <div class="stat-card">
                <div class="stat-number">{{ orders|length }}</div>
                <div>Всего заявок</div>
            </div>
            <div class="stat-card">
                <div class="stat-number">{{ orders|selectattr('status', 'equalto', 'pending')|list|length }}</div>
                <div>В ожидании</div>
            </div>
            <div class="stat-card">
                <div class="stat-number revenue">{{ orders|selectattr('status', 'equalto', 'completed')|sum(attribute='price') }}₽</div>
                <div>Доход</div>
            </div>
        </div>
        
        <div class="card">
            <h2>💰 Реквизиты для оплаты</h2>
            <p>💳 <strong>Карта:</strong> 2202 2080 1284 2135</p>
            <p>👤 <strong>Получатель:</strong> Олег Ф.</p>
            <p>📝 <strong>Комментарий:</strong> код из заявки (6 цифр)</p>
        </div>
        
        <div class="card">
            <h2>📋 Заявки на оплату</h2>
            <table>
                <thead>
                    <tr><th>Код</th><th>Тариф</th><th>Сумма</th><th>Дата</th><th>Статус</th><th>Действие</th></tr>
                </thead>
                <tbody>
                    {% for order in orders %}
                    <tr>
                        <td data-label="Код"><strong>{{ order.code }}</strong></td>
                        <td data-label="Тариф">{{ order.plan_name }}</td>
                        <td data-label="Сумма">{{ order.price }}₽</td>
                        <td data-label="Дата">{{ order.timestamp[:16] }}</td>
                        <td data-label="Статус">
                            {% if order.status == 'pending' %}
                                <span class="status-pending">⏳ Ожидает</span>
                            {% else %}
                                <span class="status-completed">✅ Выполнена</span>
                            {% endif %}
                        </td>
                        <td data-label="Действие">
                            {% if order.status == 'pending' %}
                                <form method="POST" action="/admin/confirm" style="display:inline;">
                                    <input type="hidden" name="code" value="{{ order.code }}">
                                    <button type="submit" class="btn btn-success">✅ Подтвердить</button>
                                </form>
                                <button class="btn btn-danger" onclick="deleteOrder('{{ order.code }}')">🗑️ Удалить</button>
                            {% else %}
                                <span style="color:#666;">Выполнено</span>
                            {% endif %}
                        </td>
                    </tr>
                    {% else %}
                    <tr><td colspan="6" style="text-align:center;">Нет заявок</td></tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
    
    <script>
        async function deleteOrder(code) {
            if (confirm('Удалить заявку ' + code + '?')) {
                const response = await fetch('/admin/delete/' + code, { method: 'POST' });
                if (response.ok) location.reload();
                else alert('Ошибка удаления');
            }
        }
    </script>
</body>
</html>
'''

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 VPN Server запущен на порту {port}")
    print(f"📁 Админка: http://localhost:{port}/admin")
    print(f"🌐 Сайт: https://olegmmg.github.io/")
    app.run(host='0.0.0.0', port=port, debug=False)
