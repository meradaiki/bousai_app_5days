from flask import Flask, jsonify, request, render_template, session, redirect, url_for
from urllib.parse import urlparse, urljoin
from functools import wraps
import json
import os
import urllib.request
from datetime import datetime, timedelta, timezone

# app.py はプロジェクト直下に置く。
# 実体（templates / static / data）は bousai_app/ 配下にあるので、そこを参照する。
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(BASE_DIR, 'bousai_app')

app = Flask(
    __name__,
    template_folder=os.path.join(APP_DIR, 'templates'),
    static_folder=os.path.join(APP_DIR, 'static'),
)
app.secret_key = 'your-secret-key-here'

# 管理者認証情報
ADMIN_CREDENTIALS = {
    'admin': '123'
}

# ────────────────────────────────
# 気象警報・注意報設定
PREFECTURE_CODE = "020000"  # 青森県
AREA_NAME = "青森市"

# ワークショップ課題：青森市の市区町村コードに変更する
AREA_CODE = "0220100"

WARNING_URL = (
    f"https://www.jma.go.jp/bosai/warning/data/r8/{PREFECTURE_CODE}.json"
)

JST = timezone(timedelta(hours=9))

# 警報・注意報のコード一覧
WARNING_CODES = {
    "00": "解除",
    "02": "暴風雪警報",
    "03": "レベル3大雨警報",
    "04": "洪水警報",
    "05": "暴風警報",
    "06": "大雪警報",
    "07": "波浪警報",
    "08": "レベル3高潮警報",
    "09": "レベル3土砂災害警報",
    "10": "レベル2大雨注意報",
    "12": "大雪注意報",
    "13": "風雪注意報",
    "14": "雷注意報",
    "15": "強風注意報",
    "16": "波浪注意報",
    "17": "融雪注意報",
    "18": "洪水注意報",
    "19": "レベル2高潮注意報",
    "20": "濃霧注意報",
    "21": "乾燥注意報",
    "22": "なだれ注意報",
    "23": "低温注意報",
    "24": "霜注意報",
    "25": "着氷注意報",
    "26": "着雪注意報",
    "27": "その他の注意報",
    "29": "レベル2土砂災害注意報",
    "32": "暴風雪特別警報",
    "33": "レベル5大雨特別警報",
    "35": "暴風特別警報",
    "36": "大雪特別警報",
    "37": "波浪特別警報",
    "38": "レベル5高潮特別警報",
    "39": "レベル5土砂災害特別警報",
    "43": "レベル4大雨危険警報",
    "48": "レベル4高潮危険警報",
    "49": "レベル4土砂災害危険警報"
}

# ────────────────────────────────
# サンプルデータの読み込み
DATA_FILE = os.path.join(APP_DIR, 'data', 'shelters.json')
INSTRUCTIONS_FILE = os.path.join(APP_DIR, 'data', 'instructions.json')
SHELTER_AMENITIES = [
    {'value': 'pet_allowed', 'label': 'ペット可', 'icon': '🐾'},
    {'value': 'barrier_free', 'label': 'バリアフリー', 'icon': '♿'},
    {'value': 'accessible_toilet', 'label': '多目的トイレ', 'icon': '🚻'},
    {'value': 'power_supply', 'label': '電源あり', 'icon': '🔌'},
    {'value': 'medical_support', 'label': '医療支援', 'icon': '⚕️'},
    {'value': 'baby_support', 'label': '乳幼児対応', 'icon': '🍼'},
    {'value': 'parking', 'label': '駐車場あり', 'icon': '🚗'}
]
SHELTER_AMENITY_VALUES = {amenity['value'] for amenity in SHELTER_AMENITIES}
SHELTER_HAZARDS = ('洪水', '土砂災害', '津波')

def load_json(path, default):
    """JSONファイルを読み込む（存在しない・壊れている場合は default を返す）"""
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default

shelters = load_json(DATA_FILE, [])
instructions = load_json(INSTRUCTIONS_FILE, [])


@app.context_processor
def provide_shelter_amenities():
    return {'shelter_amenities': SHELTER_AMENITIES}


def save_instructions():
    """指示ボードのデータをファイルに保存する"""
    try:
        with open(INSTRUCTIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump(instructions, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
# ────────────────────────────────

# ────────────────────────────────
# 認証関連の設定とヘルパー関数
def is_safe_url(target):
    """リダイレクト先URLが安全かどうかチェック"""
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc

def login_required(f):
    """認証が必要なページに付けるデコレータ"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            # 現在のURLをnextパラメータとしてログイン画面にリダイレクト
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def get_japan_time():
    """日本時間（JST）の現在時刻を取得する"""
    return datetime.now(JST).strftime("%Y年%m月%d日 %H:%M")


def format_report_time(iso_str):
    """気象庁の発表時刻（ISO形式）をJSTの表示用文字列に変換する"""
    if not iso_str:
        return "不明"
    try:
        parsed = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
        if parsed.tzinfo:
            parsed = parsed.astimezone(JST)
        return parsed.strftime("%Y年%m月%d日 %H:%M")
    except ValueError:
        return iso_str


def filter_shelters(
    district=None,
    q='',
    disaster='',
    pet=False,
    wheelchair=False,
    parking=False
):
    """既存の地区条件と避難所検索条件を共通のAND条件で適用する"""
    normalized_query = q.strip().casefold()

    def supports_hazard(shelter):
        hazards = shelter.get('hazards', [])
        if isinstance(hazards, str):
            hazards = [hazards]
        if isinstance(hazards, (list, tuple, set)) and disaster in hazards:
            return True
        accepted_disasters = shelter.get('accepted_disasters', '')
        return isinstance(accepted_disasters, str) and disaster in accepted_disasters

    def has_amenity(shelter, field, amenity):
        amenities = shelter.get('amenities', [])
        return shelter.get(field) is True or (
            isinstance(amenities, (list, tuple, set)) and amenity in amenities
        )

    filtered = []
    for shelter in shelters:
        if district and shelter.get('district') != district:
            continue
        if normalized_query and not any(
            normalized_query in value.casefold()
            for value in (
                shelter.get('name', ''),
                shelter.get('district', ''),
                shelter.get('address', '')
            )
            if isinstance(value, str)
        ):
            continue
        if disaster and not supports_hazard(shelter):
            continue
        if pet and not has_amenity(shelter, 'pet_allowed', 'pet_allowed'):
            continue
        if wheelchair and not has_amenity(
            shelter, 'wheelchair_accessible', 'barrier_free'
        ):
            continue
        if parking and not has_amenity(shelter, 'parking', 'parking'):
            continue
        filtered.append(shelter)
    return filtered


def get_shelter_search_values(args):
    disaster = args.get('disaster', '').strip()
    return {
        'q': args.get('q', '').strip(),
        'district': args.get('district', '').strip(),
        'disaster': disaster if disaster in SHELTER_HAZARDS else '',
        'pet': args.get('pet') in ('1', 'true', 'on'),
        'wheelchair': args.get('wheelchair') in ('1', 'true', 'on'),
        'parking': args.get('parking') in ('1', 'true', 'on')
    }


def render_shelter_results(results, search_values, status_error=None):
    return render_template(
        'search_results.html',
        results=results,
        total_count=len(shelters),
        status_error=status_error,
        **search_values
    )


def parse_area_warnings(warning_data):
    """気象庁の新形式JSONから対象市区町村の発表・継続中の情報を抽出する"""
    if not isinstance(warning_data, list):
        raise ValueError("気象庁の警報・注意報データが新形式の配列ではありません")

    warnings = []
    seen_codes = set()
    report_datetimes = []

    for report in warning_data:
        if not isinstance(report, dict):
            continue

        report_datetime = report.get("reportDatetime")
        if isinstance(report_datetime, str) and report_datetime:
            report_datetimes.append(report_datetime)

        warning = report.get("warning")
        if not isinstance(warning, dict):
            continue

        class20_items = warning.get("class20Items", [])
        if not isinstance(class20_items, list):
            continue

        area = next(
            (
                item for item in class20_items
                if isinstance(item, dict)
                and item.get("areaCode") == AREA_CODE
            ),
            None
        )
        if not area:
            continue

        kinds = area.get("kinds", [])
        if not isinstance(kinds, list):
            continue

        for kind in kinds:
            if not isinstance(kind, dict):
                continue

            status = kind.get("status", "")
            code = kind.get("code", "")
            if status not in ("発表", "継続") or not code or code in seen_codes:
                continue

            warnings.append({
                "name": WARNING_CODES.get(
                    code,
                    f"不明な警報・注意報 (コード: {code})"
                ),
                "code": code,
                "status": status
            })
            seen_codes.add(code)

    latest_report_datetime = max(report_datetimes, default="")
    return warnings, latest_report_datetime


def get_weather_warnings():
    """対象市区町村の警報・注意報を取得する"""
    try:
        # 青森県の新形式（令和8年～）警報・注意報データを取得
        with urllib.request.urlopen(url=WARNING_URL, timeout=10) as res:
            warning_data = json.loads(res.read())

        warnings, report_datetime = parse_area_warnings(warning_data)

        return {
            "area_name": AREA_NAME,
            "warnings": warnings,
            "report_time": format_report_time(report_datetime),
            "last_fetch_time": get_japan_time()
        }

    except Exception:
        return {
            "area_name": AREA_NAME,
            "warnings": [],
            "report_time": "取得失敗",
            "last_fetch_time": get_japan_time(),
            "error": True
        }


# トップページ：templates/index.html を返す（住民向け指示も表示する）
@app.route('/')
def index():
    resident_notices = [i for i in instructions if i.get('target') == '住民']
    return render_template('index.html', resident_notices=resident_notices)

# ログインページ
@app.route('/login', methods=['GET', 'POST'])
def login():
    # リダイレクト先を取得（デフォルトは避難所登録画面）
    next_url = request.args.get('next') or request.form.get('next')

    # 安全でないURLの場合はデフォルトページにリダイレクト
    if not next_url or not is_safe_url(next_url):
        next_url = url_for('shelter_register')

    if request.method == 'POST':
        password = request.form.get('password', '').strip()

        # 認証チェック
        username = next(
            (name for name, registered_password in ADMIN_CREDENTIALS.items()
             if registered_password == password),
            None
        )
        if username:
            session['logged_in'] = True
            session['username'] = username
            # ログイン成功後は指定されたページにリダイレクト
            return redirect(next_url)
        return render_template('login.html', error=True, message="パスワードが正しくありません。", next=next_url)

    # ログイン済みの場合は指定されたページにリダイレクト
    if session.get('logged_in'):
        return redirect(next_url)

    return render_template('login.html', next=next_url)

# ログアウト
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# 避難所登録ページ
@app.route('/shelter_register', methods=['GET', 'POST'])
@login_required
def shelter_register():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        form_values = {
            'name': name,
            'district': request.form.get('district', '').strip(),
            'address': request.form.get('address', '').strip(),
            'capacity': request.form.get('capacity', '').strip(),
            'current_evacuees': request.form.get('current_evacuees', '').strip(),
            'accepted_disasters': request.form.get('accepted_disasters', '').strip(),
            'hazards': [
                value for value in request.form.getlist('hazards')
                if value in SHELTER_HAZARDS
            ],
            'facilities': request.form.get('facilities', '').strip(),
            'amenities': [
                value for value in request.form.getlist('amenities')
                if value in SHELTER_AMENITY_VALUES
            ]
        }
        if not name:
            return render_template(
                'shelter_register.html', error=True, message='避難所名を入力してください。',
                form_values=form_values
            )
        if any(item.get('name') == name for item in shelters):
            return render_template(
                'shelter_register.html', error=True, message='既に登録されています',
                form_values=form_values
            )

        counts = {}
        for field, label in (
            ('capacity', '収容人数'),
            ('current_evacuees', '現在の避難者数')
        ):
            value = form_values[field]
            if not value:
                counts[field] = None
                continue
            try:
                counts[field] = int(value)
                if counts[field] < 0:
                    raise ValueError
            except ValueError:
                return render_template(
                    'shelter_register.html',
                    error=True,
                    message=f'{label}は0以上の整数で入力してください。',
                    form_values=form_values
                )

        shelter = {
            'id': max((item.get('id', 0) for item in shelters), default=0) + 1,
            'name': name,
            'district': form_values['district'],
            'address': form_values['address'],
            'capacity': counts['capacity'],
            'current_evacuees': counts['current_evacuees'],
            'accepted_disasters': form_values['accepted_disasters'],
            'hazards': form_values['hazards'],
            'pet_allowed': 'pet_allowed' in form_values['amenities'],
            'wheelchair_accessible': 'barrier_free' in form_values['amenities'],
            'parking': 'parking' in form_values['amenities'],
            'facilities': form_values['facilities'],
            'amenities': form_values['amenities']
        }
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump([*shelters, shelter], f, ensure_ascii=False, indent=2)
        shelters.append(shelter)
        return render_template(
            'shelter_register.html', success=True, message='避難所を登録しました。'
        )

    return render_template('shelter_register.html')

# 避難所検索ページ
@app.route('/shelter_search')
def shelter_search():
    search_values = get_shelter_search_values(request.args)
    results = filter_shelters(
        district=search_values['district'],
        q=search_values['q'],
        disaster=search_values['disaster'],
        pet=search_values['pet'],
        wheelchair=search_values['wheelchair'],
        parking=search_values['parking']
    )
    return render_shelter_results(results, search_values)

# 全施設一覧ページ
@app.route('/all_shelters')
def all_shelters():
    search_values = get_shelter_search_values({})
    return render_shelter_results(shelters, search_values)


@app.route('/shelter_status/<int:shelter_id>', methods=['POST'])
@login_required
def update_shelter_status(shelter_id):
    shelter = next(
        (item for item in shelters if item.get('id') == shelter_id),
        None
    )
    if shelter is None:
        return '避難所が見つかりません。', 404

    values = {
        'capacity': request.form.get('capacity', '').strip(),
        'current_evacuees': request.form.get('current_evacuees', '').strip()
    }
    counts = {}
    for field, label in (
        ('capacity', '収容人数'),
        ('current_evacuees', '現在の避難者数')
    ):
        try:
            counts[field] = int(values[field])
            if counts[field] < 0:
                raise ValueError
        except ValueError:
            search_values = get_shelter_search_values(request.args)
            results = filter_shelters(
                district=search_values['district'],
                q=search_values['q'],
                disaster=search_values['disaster'],
                pet=search_values['pet'],
                wheelchair=search_values['wheelchair'],
                parking=search_values['parking']
            )
            return render_shelter_results(
                results,
                search_values,
                status_error=f'{label}は0以上の整数で入力してください。'
            )

    shelter.update(counts)
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(shelters, f, ensure_ascii=False, indent=2)

    query_params = request.args.to_dict()
    if query_params:
        return redirect(url_for('search_results', **query_params))
    return redirect(url_for('all_shelters'))


# 指示ボード：住民向けの指示を一覧で確認する
@app.route('/board')
@login_required
def board():
    resident_instructions = [i for i in instructions if i.get('target') == '住民']
    return render_template('board.html', instructions=resident_instructions)

# 検索結果ページ：templates/search_results.html を返す
@app.route('/search_results')
def search_results():
    search_values = get_shelter_search_values(request.args)
    results = filter_shelters(
        district=search_values['district'],
        q=search_values['q'],
        disaster=search_values['disaster'],
        pet=search_values['pet'],
        wheelchair=search_values['wheelchair'],
        parking=search_values['parking']
    )
    return render_shelter_results(results, search_values)

# JSON API：/shelters?district=地区名
@app.route('/shelters', methods=['GET'])
def get_shelters():
    search_values = get_shelter_search_values(request.args)
    results = filter_shelters(
        district=search_values['district'],
        q=search_values['q'],
        disaster=search_values['disaster'],
        pet=search_values['pet'],
        wheelchair=search_values['wheelchair'],
        parking=search_values['parking']
    )

    if not results:
        # 見つからなければエラー JSON を返す
        return jsonify({'error': 'No shelters found'}), 404

    # 見つかったらリストを JSON で返す
    return jsonify(results)

# 気象警報・注意報API
@app.route('/api/weather_warnings')
def api_weather_warnings():
    """気象警報・注意報をJSON形式で返すAPI"""
    return jsonify(get_weather_warnings())

if __name__ == '__main__':
    app.run(debug=True, port=5000)
