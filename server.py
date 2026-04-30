#!/usr/bin/env python3
"""
VPN Subscription Server for Render.com
- API для создания подписок и заявок
- Полная админ-панель для управления подписками
- Синхронизация всех подписок с шаблоном
"""

import os, json, base64, random, string, re
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
        return url, f"Действительна до {expire_date}", expire_ts
    return None, "Ошибка сохранения", None

def sync_all_subscriptions():
    """Синхронизирует все подписки с актуальным шаблоном"""
    results = {"main": {"updated": 0, "failed": 0}, "test": {"updated": 0, "failed": 0}}
    
    for sub_type in ["main", "test"]:
        template = get_file_content(TEMPLATES[sub_type]["template_path"])
        if not template:
            results[sub_type]["failed"] = -1
            continue
        
        files = list_files_in_dir(TEMPLATES[sub_type]["output_dir"])
        for filename in files:
            path = f"{TEMPLATES[sub_type]['output_dir']}/{filename}"
            try:
                existing_file = repo.get_contents(path, ref=BRANCH)
                old_content = base64.b64decode(existing_file.content).decode('utf-8')
                
                # Извлекаем старую дату
                old_userinfo = None
                for line in old_content.split('\n'):
                    if line.startswith('#subscription-userinfo:'):
                        old_userinfo = line
                        break
                
                if old_userinfo:
                    new_content = old_userinfo + '\n' + template
                else:
                    new_content = template
                
                repo.update_file(path, f"Синхронизация с шаблоном", new_content, existing_file.sha, branch=BRANCH)
                results[sub_type]["updated"] += 1
            except Exception as e:
                results[sub_type]["failed"] += 1
                print(f"❌ Ошибка {filename}: {e}")
    
    return results

def get_all_subscriptions():
    """Получает список всех подписок с их датами"""
    subscriptions = []
    for sub_type in ["main", "test"]:
        output_dir = TEMPLATES[sub_type]["output_dir"]
        files = list_files_in_dir(output_dir)
        for filename in files:
            path = f"{output_dir}/{filename}"
            content = get_file_content(path)
            expire_date = "не указана"
            expire_ts = None
            if content:
                for line in content.split('\n'):
                    if 'expire=' in line:
                        try:
                            expire_ts = int(line.split('expire=')[1].split(';')[0])
                            expire_date = datetime.fromtimestamp(expire_ts).strftime("%d.%m.%Y")
                        except:
                            pass
                        break
            subscriptions.append({
                "type": sub_type,
                "type_name": TEMPLATES[sub_type]["name"],
                "filename": filename,
                "path": path,
                "url": f"https://olegmmg.github.io/{path}",
                "expire_date": expire_date,
                "expire_ts": expire_ts
            })
    return subscriptions

# ========== HTTP ЭНДПОИНТЫ ==========

@app.route('/')
def index():
    return redirect("https://olegmmg.github.io/")

@app.route('/api/create', methods=['POST'])
def api_create():
    data = request.json
    sub_type = data.get('type', 'main')
    duration = data.get('duration', '1m')
    url, msg, ts = create_subscription(sub_type, duration)
    if url:
        return jsonify({'success': True, 'url': url, 'message': msg})
    return jsonify({'success': False, 'error': msg})

@app.route('/api/create-order', methods=['POST'])
def create_order():
    data = request.json
    code = data.get('code')
    if not code:
        return jsonify({'success': False, 'error': 'Нет кода'})
    
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

# ========== ПОЛНАЯ АДМИН-ПАНЕЛЬ ==========

@app.route('/admin')
def admin():
    if not repo:
        return "<h1>❌ GitHub не настроен</h1><p>Укажите GITHUB_TOKEN</p>"
    
    # Получаем заявки
    orders = []
    try:
        contents = repo.get_contents("orders", ref=BRANCH)
        for c in contents:
            if c.name.endswith('.json'):
                data = json.loads(base64.b64decode(c.content).decode())
                orders.append(data)
        orders.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    except:
        pass
    
    # Получаем подписки
    subscriptions = get_all_subscriptions()
    
    # Получаем содержимое шаблонов
    main_template = get_file_content("vpn/sub") or "Шаблон не найден"
    test_template = get_file_content("vpn/test") or "Шаблон не найден"
    
    return render_template_string(ADMIN_TEMPLATE, 
                                  orders=orders, 
                                  subscriptions=subscriptions,
                                  main_template=main_template[:500] + "...",
                                  test_template=test_template[:500] + "...")

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
    
    url, msg, ts = create_subscription(sub_type, duration)
    
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
        return f"<h1>❌ Ошибка</h1><p>{msg}</p><a href='/admin'>← Назад</a>"

@app.route('/admin/delete-order/<code>', methods=['POST'])
def delete_order(code):
    path = f"orders/{code}.json"
    if delete_file(path):
        return '', 204
    return '', 404

@app.route('/admin/delete-subscription', methods=['POST'])
def delete_subscription():
    path = request.form.get('path')
    if path and delete_file(path):
        return '', 204
    return '', 404

@app.route('/admin/sync-templates', methods=['POST'])
def sync_templates():
    results = sync_all_subscriptions()
    return jsonify(results)

@app.route('/admin/update-template', methods=['POST'])
def update_template():
    template_type = request.form.get('type')  # main или test
    content = request.form.get('content')
    
    if template_type == 'main':
        path = "vpn/sub"
    else:
        path = "vpn/test"
    
    if save_file(path, content, f"Обновлён шаблон {template_type}"):
        return jsonify({'success': True})
    return jsonify({'success': False})

# ========== ШАБЛОН АДМИН-ПАНЕЛИ ==========

ADMIN_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>VPN Admin Panel</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f0f2f5; padding: 20px; }
        .container { max-width: 1400px; margin: 0 auto; }
        h1 { color: #1a73e8; margin-bottom: 20px; }
        h2 { margin-bottom: 15px; color: #333; font-size: 1.3em; }
        .card { background: white; border-radius: 16px; padding: 20px; margin-bottom: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
        .tabs { display: flex; gap: 5px; margin-bottom: 20px; flex-wrap: wrap; }
        .tab-btn { padding: 10px 20px; border: none; background: #e2e8f0; border-radius: 10px; cursor: pointer; font-size: 14px; }
        .tab-btn.active { background: #1a73e8; color: white; }
        .tab-content { display: none; }
        .tab-content.active { display: block; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 12px; text-align: left; border-bottom: 1px solid #e2e8f0; }
        th { background: #f8f9fa; font-weight: 600; color: #1a73e8; }
        tr:hover { background: #f8f9fa; }
        .status-pending { background: #ffc107; padding: 4px 12px; border-radius: 20px; font-size: 12px; display: inline-block; }
        .status-completed { background: #28a745; color: white; padding: 4px 12px; border-radius: 20px; font-size: 12px; display: inline-block; }
        .btn { padding: 8px 16px; border: none; border-radius: 8px; cursor: pointer; font-size: 13px; transition: 0.2s; }
        .btn-success { background: #28a745; color: white; }
        .btn-success:hover { background: #218838; }
        .btn-danger { background: #dc3545; color: white; }
        .btn-danger:hover { background: #c82333; }
        .btn-primary { background: #1a73e8; color: white; }
        .btn-primary:hover { background: #1557b0; }
        .btn-warning { background: #ffc107; color: #333; }
        .btn-warning:hover { background: #e0a800; }
        form { display: inline; }
        .stats { display: flex; gap: 20px; flex-wrap: wrap; margin-bottom: 20px; }
        .stat-card { background: white; border-radius: 16px; padding: 20px; flex: 1; min-width: 150px; text-align: center; }
        .stat-number { font-size: 2em; font-weight: bold; color: #1a73e8; }
        .revenue { color: #28a745; }
        .expired { color: #dc3545; }
        textarea { width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 8px; font-family: monospace; font-size: 12px; }
        .flex { display: flex; gap: 20px; flex-wrap: wrap; }
        .flex > div { flex: 1; }
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
            <div class="stat-card">
                <div class="stat-number">{{ subscriptions|length }}</div>
                <div>Активных подписок</div>
            </div>
        </div>
        
        <div class="tabs">
            <button class="tab-btn active" onclick="showTab('orders')">📋 Заявки</button>
            <button class="tab-btn" onclick="showTab('subscriptions')">🔑 Подписки</button>
            <button class="tab-btn" onclick="showTab('templates')">📝 Шаблоны</button>
            <button class="tab-btn" onclick="showTab('settings')">💰 Реквизиты</button>
        </div>
        
        <!-- Вкладка: Заявки -->
        <div id="tab-orders" class="tab-content active">
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
                                    <button class="btn btn-danger" onclick="deleteOrder('{{ order.code }}')">🗑️</button>
                                {% endif %}
                            </td>
                        </tr>
                        {% else %}
                        <tr><td colspan="6">Нет заявок</td></tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
        
        <!-- Вкладка: Подписки -->
        <div id="tab-subscriptions" class="tab-content">
            <div class="card">
                <h2>🔑 Созданные подписки</h2>
                <button class="btn btn-warning" onclick="syncTemplates()" style="margin-bottom: 15px;">🔄 Синхронизировать все подписки с шаблонами</button>
                <div id="syncResult" style="margin-bottom: 15px;"></div>
                <table>
                    <thead>
                        <tr><th>Тип</th><th>Файл</th><th>Действительна до</th><th>Ссылка</th><th>Действие</th></tr>
                    </thead>
                    <tbody>
                        {% for sub in subscriptions %}
                        <tr>
                            <td data-label="Тип">{{ sub.type_name }}</td>
                            <td data-label="Файл"><code>{{ sub.filename }}</code></td>
                            <td data-label="Действительна до">
                                {{ sub.expire_date }}
                                {% if sub.expire_ts and sub.expire_ts < now %}<span style="color:red;"> (Истекла)</span>{% endif %}
                            </td>
                            <td data-label="Ссылка"><a href="{{ sub.url }}" target="_blank">{{ sub.url[:50] }}...</a></td>
                            <td data-label="Действие">
                                <form method="POST" action="/admin/delete-subscription" style="display:inline;">
                                    <input type="hidden" name="path" value="{{ sub.path }}">
                                    <button type="submit" class="btn btn-danger" onclick="return confirm('Удалить?')">🗑️</button>
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
        
        <!-- Вкладка: Шаблоны -->
        <div id="tab-templates" class="tab-content">
            <div class="card">
                <h2>📝 Редактирование шаблонов</h2>
                <div class="flex">
                    <div>
                        <h3>🇷🇺 Основная подписка (vpn/sub)</h3>
                        <textarea id="mainTemplate" rows="15" style="width:100%">{{ main_template }}</textarea>
                        <button class="btn btn-primary" onclick="updateTemplate('main')" style="margin-top:10px">💾 Сохранить основную</button>
                    </div>
                    <div>
                        <h3>🧪 Тестовая подписка (vpn/test)</h3>
                        <textarea id="testTemplate" rows="15" style="width:100%">{{ test_template }}</textarea>
                        <button class="btn btn-primary" onclick="updateTemplate('test')" style="margin-top:10px">💾 Сохранить тестовую</button>
                    </div>
                </div>
                <p style="margin-top:15px; font-size:12px; color:#666;">
                    ⚠️ После обновления шаблонов нажмите «Синхронизировать все подписки», чтобы обновить уже созданные подписки (даты окончания сохранятся).
                </p>
            </div>
        </div>
        
        <!-- Вкладка: Настройки -->
        <div id="tab-settings" class="tab-content">
            <div class="card">
                <h2>💰 Реквизиты для оплаты</h2>
                <p>💳 <strong>Карта:</strong> 2202 2080 1284 2135</p>
                <p>👤 <strong>Получатель:</strong> Олег Ф.</p>
                <p>📝 <strong>Комментарий:</strong> код из заявки (6 цифр)</p>
                <hr style="margin: 20px 0;">
                <h2>📌 Памятка</h2>
                <ol>
                    <li>Пользователь выбирает тариф → получает 6-значный код</li>
                    <li>Переводит деньги на карту с комментарием = код</li>
                    <li>Нажимает «Я оплатил» → заявка появляется здесь</li>
                    <li>Вы проверяете банк по коду → нажимаете «Подтвердить»</li>
                    <li>Подписка создаётся автоматически</li>
                </ol>
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
        
        async function deleteOrder(code) {
            if (confirm('Удалить заявку ' + code + '?')) {
                await fetch('/admin/delete-order/' + code, { method: 'POST' });
                location.reload();
            }
        }
        
        async function syncTemplates() {
            const btn = event.target;
            const originalText = btn.textContent;
            btn.textContent = '🔄 Синхронизация...';
            btn.disabled = true;
            
            const response = await fetch('/admin/sync-templates', { method: 'POST' });
            const data = await response.json();
            
            document.getElementById('syncResult').innerHTML = `
                <div style="background:#d4edda; padding:10px; border-radius:8px;">
                    ✅ Обновлено: Основные ${data.main.updated}, Тестовые ${data.test.updated}<br>
                    ❌ Ошибок: ${data.main.failed + data.test.failed}
                </div>
            `;
            setTimeout(() => location.reload(), 1500);
        }
        
        async function updateTemplate(type) {
            const content = document.getElementById(type + 'Template').value;
            const response = await fetch('/admin/update-template', {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: `type=${type}&content=${encodeURIComponent(content)}`
            });
            const data = await response.json();
            if (data.success) {
                alert('✅ Шаблон сохранён! Не забудьте синхронизировать подписки.');
            } else {
                alert('❌ Ошибка сохранения');
            }
        }
    </script>
</body>
</html>
'''

from flask import redirect

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 VPN Server запущен на порту {port}")
    print(f"📁 Админка: http://localhost:{port}/admin")
    app.run(host='0.0.0.0', port=port, debug=False)
