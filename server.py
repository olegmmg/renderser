#!/usr/bin/env python3
"""
VPN Subscription Server for Render.com
"""

import os, json, base64, random, string, re
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template_string, redirect
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

# ========== ПАРАМЕТРЫ ==========
TEMPLATES = {
    "main": {"name": "Основная", "template_path": "vpn/sub", "output_dir": "vpn/subs"},
    "test": {"name": "Тестовая", "template_path": "vpn/test", "output_dir": "vpn/tests"}
}

PRICES = {"main": {"7d": 0, "1m": 20, "3m": 50, "12m": 180}, "test": {"7d": 0, "1m": 30, "3m": 75, "12m": 270}}
DAYS_MAP = {"7d": 7, "1m": 30, "3m": 90, "12m": 365}

def create_subscription(sub_type, duration):
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
        return f"https://olegmmg.github.io/{path}", f"Действительна до {expire_date}"
    return None, "Ошибка сохранения"

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
            if content:
                for line in content.split('\n'):
                    if 'expire=' in line:
                        try:
                            ts = int(line.split('expire=')[1].split(';')[0])
                            expire_date = datetime.fromtimestamp(ts).strftime("%d.%m.%Y")
                        except: pass
                        break
            subs.append({
                "type": sub_type,
                "type_name": TEMPLATES[sub_type]["name"],
                "filename": filename,
                "path": path,
                "url": f"https://olegmmg.github.io/{path}",
                "expire_date": expire_date
            })
    return subs

# ========== ЭНДПОИНТЫ ==========
@app.route('/')
def index():
    return redirect("https://olegmmg.github.io/")

@app.route('/api/create', methods=['POST'])
def api_create():
    data = request.json
    url, msg = create_subscription(data.get('type', 'main'), data.get('duration', '1m'))
    if url:
        return jsonify({'success': True, 'url': url, 'message': msg})
    return jsonify({'success': False, 'error': msg})

# ========== ТЁМНАЯ АДМИН-ПАНЕЛЬ ==========
@app.route('/admin', methods=['GET', 'POST'])
def admin():
    main_subs = []
    test_subs = []
    for sub in get_all_subscriptions():
        if sub['type'] == 'main':
            main_subs.append(sub)
        else:
            test_subs.append(sub)
    
    message = None
    message_type = None
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'create':
            sub_type = request.form.get('subscription_type')
            duration = request.form.get('duration')
            url, msg = create_subscription(sub_type, duration)
            if url:
                message = f"✅ Подписка создана!<br>🔗 {url}<br>📅 {msg}"
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
    
    return render_template_string(ADMIN_TEMPLATE, main_subs=main_subs, test_subs=test_subs, message=message, message_type=message_type)

ADMIN_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>VPN Admin Panel</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0a0e1a; padding: 20px; color: #e2e8f0; }
        .container { max-width: 1400px; margin: 0 auto; }
        h1 { color: #60a5fa; margin-bottom: 20px; }
        h2 { margin: 0 0 15px 0; color: #94a3b8; border-bottom: 2px solid #3b82f6; display: inline-block; padding-bottom: 5px; }
        .card { background: #111827; border-radius: 16px; padding: 20px; margin-bottom: 20px; border: 1px solid #1f2937; }
        .btn { padding: 10px 20px; margin: 5px; border: none; border-radius: 8px; cursor: pointer; font-size: 14px; transition: 0.2s; }
        .btn-primary { background: #3b82f6; color: white; }
        .btn-primary:hover { background: #2563eb; }
        .btn-danger { background: #ef4444; color: white; }
        .btn-danger:hover { background: #dc2626; }
        .btn-success { background: #22c55e; color: white; }
        .btn-success:hover { background: #16a34a; }
        .btn-warning { background: #f59e0b; color: #1a1a2e; }
        .btn-warning:hover { background: #d97706; }
        table { width: 100%; border-collapse: collapse; margin-top: 15px; }
        th, td { padding: 12px; text-align: left; border-bottom: 1px solid #1f2937; }
        th { background: #0f1622; color: #60a5fa; }
        tr:hover { background: #1a2332; }
        code { background: #1f2937; padding: 2px 6px; border-radius: 4px; font-family: monospace; font-size: 11px; color: #94a3b8; word-break: break-all; }
        select, input { background: #1f2937; color: #e2e8f0; border: 1px solid #374151; padding: 8px; border-radius: 6px; width: 100%; }
        .price-table { display: flex; gap: 20px; margin: 20px 0; flex-wrap: wrap; }
        .price-card { flex: 1; background: #0f1622; border-radius: 12px; padding: 15px; text-align: center; border: 1px solid #1f2937; }
        .price-card h3 { margin: 0 0 10px 0; }
        .price-card .price { font-size: 24px; font-weight: bold; color: #60a5fa; }
        .price-card.main { border-top: 3px solid #3b82f6; }
        .price-card.test { border-top: 3px solid #22c55e; }
        .row { display: flex; gap: 20px; flex-wrap: wrap; }
        .col { flex: 1; min-width: 300px; }
        .success { background: #065f46; color: #d1fae5; padding: 15px; border-radius: 12px; margin-bottom: 20px; }
        .error { background: #991b1b; color: #fecaca; padding: 15px; border-radius: 12px; margin-bottom: 20px; }
        .warning { background: #92400e; color: #fef3c7; padding: 15px; border-radius: 12px; margin-bottom: 20px; }
        .badge-trial { background: #8b5cf6; color: white; padding: 2px 8px; border-radius: 12px; font-size: 10px; margin-left: 8px; }
        @media (max-width: 768px) {
            .row { flex-direction: column; }
            table, thead, tbody, th, td, tr { display: block; }
            thead { display: none; }
            tr { margin-bottom: 15px; border: 1px solid #1f2937; border-radius: 12px; padding: 10px; }
            td { display: flex; justify-content: space-between; align-items: center; padding: 8px; border: none; }
            td:before { content: attr(data-label); font-weight: bold; margin-right: 10px; color: #60a5fa; }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🔐 VPN Admin Panel</h1>
        
        {% if message %}
        <div class="{{ message_type }}">{{ message | safe }}</div>
        {% endif %}
        
        <div class="row">
            <div class="col">
                <div class="card">
                    <h2>💰 Цены</h2>
                    <div class="price-table">
                        <div class="price-card main">
                            <h3>🇷🇺 ОСНОВНАЯ</h3>
                            <div class="price">0₽ / 7 дней</div>
                            <div class="price">20₽ / месяц</div>
                            <div>50₽ / 3 месяца</div>
                            <div>180₽ / год</div>
                        </div>
                        <div class="price-card test">
                            <h3>🧪 ТЕСТОВАЯ</h3>
                            <div class="price">0₽ / 7 дней</div>
                            <div class="price">30₽ / месяц</div>
                            <div>75₽ / 3 месяца</div>
                            <div>270₽ / год</div>
                        </div>
                    </div>
                </div>
            </div>
            <div class="col">
                <div class="card">
                    <h2>➕ Создать подписку</h2>
                    <form method="POST">
                        <div style="margin-bottom: 15px;">
                            <label style="display: block; margin-bottom: 5px;">Тип:</label>
                            <select name="subscription_type">
                                <option value="main">🇷🇺 Основная</option>
                                <option value="test">🧪 Тестовая</option>
                            </select>
                        </div>
                        <div style="margin-bottom: 15px;">
                            <label style="display: block; margin-bottom: 5px;">Срок:</label>
                            <select name="duration">
                                <option value="7d">🎁 Пробная (7 дней) — 0₽</option>
                                <option value="1m">1 месяц</option>
                                <option value="3m">3 месяца</option>
                                <option value="12m">1 год</option>
                            </select>
                        </div>
                        <button type="submit" name="action" value="create" class="btn btn-primary" style="width: 100%;">Создать подписку</button>
                    </form>
                </div>
            </div>
        </div>
        
        <div class="card">
            <h2>🔄 Синхронизация</h2>
            <p>Обновляет все подписки по текущим шаблонам (даты окончания сохраняются).</p>
            <form method="POST">
                <button type="submit" name="action" value="sync" class="btn btn-warning">🔄 Синхронизировать все подписки</button>
            </form>
        </div>
        
        <div class="card">
            <h2>📋 Основные подписки (vpn/subs)</h2>
            <table>
                <thead><tr><th>Файл</th><th>Действительна до</th><th>Ссылка</th><th></th></tr></thead>
                <tbody>
                    {% for sub in main_subs %}
                    <tr>
                        <td data-label="Файл"><code>{{ sub.filename }}</code></td>
                        <td data-label="Действительна до">{{ sub.expire_date }}</td>
                        <td data-label="Ссылка"><code style="font-size: 9px;">{{ sub.url }}</code></td>
                        <td data-label="Действие">
                            <form method="POST" style="display:inline;">
                                <input type="hidden" name="delete_type" value="main">
                                <input type="hidden" name="delete_file" value="{{ sub.filename }}">
                                <button type="submit" name="action" value="delete" class="btn-danger" style="padding: 5px 10px;">🗑️</button>
                            </form>
                        </td>
                    </tr>
                    {% else %}
                    <tr><td colspan="4">Нет созданных подписок</td></tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        
        <div class="card">
            <h2>🧪 Тестовые подписки (vpn/tests)</h2>
            <table>
                <thead><tr><th>Файл</th><th>Действительна до</th><th>Ссылка</th><th></th></tr></thead>
                <tbody>
                    {% for sub in test_subs %}
                    <tr>
                        <td data-label="Файл"><code>{{ sub.filename }}</code></td>
                        <td data-label="Действительна до">{{ sub.expire_date }}</td>
                        <td data-label="Ссылка"><code style="font-size: 9px;">{{ sub.url }}</code></td>
                        <td data-label="Действие">
                            <form method="POST" style="display:inline;">
                                <input type="hidden" name="delete_type" value="test">
                                <input type="hidden" name="delete_file" value="{{ sub.filename }}">
                                <button type="submit" name="action" value="delete" class="btn-danger" style="padding: 5px 10px;">🗑️</button>
                            </form>
                        </td>
                    </tr>
                    {% else %}
                    <tr><td colspan="4">Нет созданных подписок</td></tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        
        <div class="card">
            <h2>💰 Реквизиты для оплаты</h2>
            <p>💳 <strong>Карта:</strong> 2202 2080 1284 2135</p>
            <p>👤 <strong>Получатель:</strong> Олег Ф.</p>
            <p>📝 <strong>Комментарий:</strong> код из заявки (6 цифр)</p>
        </div>
    </div>
</body>
</html>
'''

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 VPN Server запущен на порту {port}")
    print(f"📁 Админка: http://localhost:{port}/admin")
    app.run(host='0.0.0.0', port=port, debug=False)
