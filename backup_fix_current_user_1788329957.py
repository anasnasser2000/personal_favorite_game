from pathlib import Path
from datetime import datetime
from sqlalchemy import or_, and_

from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
from functools import wraps
import secrets
import string
import os
import json
import threading
import urllib.request
import urllib.parse


app = Flask(__name__)
app.config["SECRET_KEY"] = "personal-favorite-game-secret-change-later"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///../data/game.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


# =========================================================
# SECTION 10 - RATINGS
# =========================================================

class Rating(db.Model):
    __tablename__ = "ratings"

    id = db.Column(db.Integer, primary_key=True)

    rater_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )

    rated_user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )

    score = db.Column(
        db.Integer,
        nullable=False
    )

    comment = db.Column(db.Text, nullable=True)

    created_at = db.Column(
        db.DateTime,
        server_default=db.func.now()
    )

    __table_args__ = (
        db.UniqueConstraint(
            "rater_id",
            "rated_user_id",
            name="unique_user_rating"
        ),
    )


def get_user_rating_info(user_id):
    ratings = Rating.query.filter_by(
        rated_user_id=user_id
    ).all()

    if not ratings:
        return {
            "average": 0,
            "count": 0
        }

    total = sum(r.score for r in ratings)
    average = round(total / len(ratings), 2)

    return {
        "average": average,
        "count": len(ratings)
    }


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped






@app.route("/rating/<int:user_id>", methods=["GET", "POST"])
@login_required
def rating_page(user_id):

    rated_user = db.session.get(User, user_id)

    if not rated_user:
        flash("المستخدم غير موجود", "error")
        return redirect(url_for("home"))

    if rated_user.id == session["user_id"]:
        flash("ما تقدرش تقيم نفسك", "error")
        return redirect(url_for("home"))

    existing = Rating.query.filter_by(
        rater_id=session["user_id"],
        rated_user_id=rated_user.id
    ).first()

    if request.method == "POST":

        try:
            score = int(request.form.get("score", 0))
        except:
            score = 0

        comment = request.form.get(
            "comment",
            ""
        ).strip()

        if score < 1 or score > 5:
            flash("اختار تقييم من 1 إلى 5 نجوم", "error")
            return redirect(url_for(
                "rating_page",
                user_id=user_id
            ))

        if existing:
            existing.score = score
            existing.comment = comment
        else:
            rating = Rating(
                rater_id=session["user_id"],
                rated_user_id=rated_user.id,
                score=score,
                comment=comment
            )

            db.session.add(rating)

        db.session.commit()

        flash("تم حفظ تقييمك ⭐", "success")

        return redirect(url_for(
            "rating_page",
            user_id=user_id
        ))

    info = get_user_rating_info(rated_user.id)

    return render_template(
        "rating.html",
        rated_user=rated_user,
        existing=existing,
        average=info["average"],
        rating_count=info["count"]
    )


@app.route("/api/rating", methods=["POST"])
@login_required
def api_rating():

    data = request.get_json(silent=True) or {}

    try:
        rated_user_id = int(data.get("rated_user_id", 0))
        score = int(data.get("score", 0))
    except:
        return {
            "ok": False,
            "error": "invalid_data"
        }, 400

    comment = str(
        data.get("comment", "")
    ).strip()

    if rated_user_id <= 0:
        return {
            "ok": False,
            "error": "invalid_user"
        }, 400

    if score < 1 or score > 5:
        return {
            "ok": False,
            "error": "score_must_be_1_to_5"
        }, 400

    if rated_user_id == session["user_id"]:
        return {
            "ok": False,
            "error": "cannot_rate_yourself"
        }, 400

    rated_user = db.session.get(User, rated_user_id)

    if not rated_user:
        return {
            "ok": False,
            "error": "user_not_found"
        }, 404

    existing = Rating.query.filter_by(
        rater_id=session["user_id"],
        rated_user_id=rated_user_id
    ).first()

    if existing:
        existing.score = score
        existing.comment = comment
    else:
        db.session.add(
            Rating(
                rater_id=session["user_id"],
                rated_user_id=rated_user_id,
                score=score,
                comment=comment
            )
        )

    db.session.commit()

    info = get_user_rating_info(rated_user_id)

    return {
        "ok": True,
        "average": info["average"],
        "count": info["count"]
    }


@app.route("/api/rating/<int:user_id>")
@login_required
def api_user_rating(user_id):

    user = db.session.get(User, user_id)

    if not user:
        return {
            "ok": False,
            "error": "user_not_found"
        }, 404

    info = get_user_rating_info(user.id)

    return {
        "ok": True,
        "user_id": user.id,
        "player_id": user.player_id,
        "average": info["average"],
        "count": info["count"]
    }

# =========================================================
# SECTION 9 - NOTIFICATIONS + TELEGRAM
# =========================================================

TELEGRAM_BOT_TOKEN = os.environ.get(
    "TELEGRAM_BOT_TOKEN",
    ""
)

TELEGRAM_CHAT_ID = os.environ.get(
    "TELEGRAM_CHAT_ID",
    ""
)


def send_telegram(message):
    """
    إرسال رسالة Telegram.
    يتم استدعاؤها في Thread حتى لا تعطل الصفحة.
    """

    if not TELEGRAM_BOT_TOKEN:
        return

    if not TELEGRAM_CHAT_ID:
        return

    try:

        url = (
            "https://api.telegram.org/bot"
            + TELEGRAM_BOT_TOKEN
            + "/sendMessage"
        )

        data = urllib.parse.urlencode({
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message
        }).encode("utf-8")

        request = urllib.request.Request(
            url,
            data=data,
            method="POST"
        )

        urllib.request.urlopen(
            request,
            timeout=8
        ).read()

    except Exception:
        pass


def send_telegram_background(message):

    thread = threading.Thread(
        target=send_telegram,
        args=(message,),
        daemon=True
    )

    thread.start()


def telegram_user_text(user):

    if not user:
        return "مستخدم غير معروف"

    return (
        f"👤 {user.name}\n"
        f"🔹 @{user.username}\n"
        f"🆔 ID: {user.player_id}"
    )





class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.String(8), unique=True, nullable=False)
    username = db.Column(db.String(40), unique=True, nullable=False)
    name = db.Column(db.String(80), nullable=False)
    father_name = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)


    
class Profile(db.Model):
    __tablename__ = "profiles"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        unique=True,
        nullable=False
    )
    avatar_filename = db.Column(db.String(255), nullable=True)
    created_at = db.Column(
        db.DateTime,
        server_default=db.func.now()
    )

    
class ChatMessage(db.Model):
    __tablename__ = "chat_messages"

    id = db.Column(db.Integer, primary_key=True)

    sender_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )

    receiver_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )

    message = db.Column(
        db.Text,
        nullable=False
    )

    created_at = db.Column(
        db.DateTime,
        server_default=db.func.now()
    )


class Notification(db.Model):
    __tablename__ = "notifications"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )

    title = db.Column(
        db.String(150),
        nullable=False
    )

    message = db.Column(
        db.Text,
        nullable=False
    )

    notification_type = db.Column(
        db.String(50),
        nullable=False,
        default="general"
    )

    is_read = db.Column(
        db.Boolean,
        nullable=False,
        default=False
    )

    created_at = db.Column(
        db.DateTime,
        server_default=db.func.now()
    )

class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(40), nullable=False)
    card_number = db.Column(db.Integer, nullable=False)
    question_number = db.Column(db.Integer, nullable=False)
    text = db.Column(db.Text, nullable=False)

    __table_args__ = (
        db.UniqueConstraint(
            "category",
            "card_number",
            "question_number",
            name="unique_question_position"
        ),
    )


class Answer(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )

    question_id = db.Column(
        db.Integer,
        db.ForeignKey("question.id"),
        nullable=False
    )

    # 10 = أعطى 10 نقاط
    # 0 = أعطى 0 نقاط
    # skip = لم يجب / تخطى
    value = db.Column(db.String(10), nullable=False)
    answer_text = db.Column(db.Text, nullable=True)

    points = db.Column(db.Integer, nullable=False, default=0)

    created_at = db.Column(
        db.DateTime,
        server_default=db.func.now()
    )

    __table_args__ = (
        db.UniqueConstraint(
            "user_id",
            "question_id",
            name="unique_user_question_answer"
        ),
    )



def generate_room_code():
    alphabet = string.ascii_uppercase + string.digits
    while True:
        code = "".join(secrets.choice(alphabet) for _ in range(6))
        if not Room.query.filter_by(room_code=code).first():
            return code


def generate_player_id():
    while True:
        value = "".join(secrets.choice(string.digits) for _ in range(8))
        if not User.query.filter_by(player_id=value).first():
            return value


def create_notification(
    user_id,
    title,
    message,
    notification_type="general"
):

    notification = Notification(
        user_id=user_id,
        title=title,
        message=message,
        notification_type=notification_type
    )

    db.session.add(notification)
    db.session.commit()

    return notification


def notify_and_telegram(
    user_id,
    title,
    message,
    notification_type="general",
    telegram_message=None
):

    try:

        create_notification(
            user_id,
            title,
            message,
            notification_type
        )

    except Exception:
        db.session.rollback()

    if telegram_message:
        send_telegram_background(
            telegram_message
        )



@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("home"))
    return render_template("welcome.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        name = request.form.get("name", "").strip()
        father_name = request.form.get("father_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not all([username, name, father_name, email, password, confirm_password]):
            flash("لازم تعبي كل البيانات.")
            return render_template("register.html")

        if len(username) < 3:
            flash("اسم المستخدم لازم يكون 3 أحرف أو أكثر.")
            return render_template("register.html")

        if len(password) < 6:
            flash("كلمة السر لازم تكون 6 أحرف أو أكثر.")
            return render_template("register.html")

        if password != confirm_password:
            flash("كلمتا السر مش متطابقات.")
            return render_template("register.html")

        if User.query.filter_by(username=username).first():
            flash("اسم المستخدم مستخدم بالفعل.")
            return render_template("register.html")

        if User.query.filter_by(email=email).first():
            flash("الإيميل مستخدم بالفعل.")
            return render_template("register.html")

        user = User(
            player_id=generate_player_id(),
            username=username,
            name=name,
            father_name=father_name,
            email=email,
            password_hash=generate_password_hash(password)
        )

        db.session.add(user)
        db.session.commit()

        session["user_id"] = user.id
        return redirect(url_for("home"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip()
        password = request.form.get("password", "")

        user = User.query.filter(
            or_(
                User.username == identifier,
                User.email == identifier.lower()
            )
        ).first()

        if not user or not check_password_hash(user.password_hash, password):
            flash("بيانات الدخول غلط.")
            return render_template("login.html")

        session["user_id"] = user.id
        return redirect(url_for("home"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/home")
@login_required
def home():
    user = db.session.get(User, session["user_id"])
    return render_template("home.html", user=user)



@app.route("/join-room")
@login_required
def join_room_page():
    return render_template("join_room.html")


@app.route("/mode")
@login_required
def mode():
    return render_template("mode.html")


@app.route("/categories")
@login_required
def categories():
    return render_template("categories.html")


@app.route("/category/<slug>")
@login_required
def category(slug):
    categories_data = {
        "single": ("🎮 لعب بروحي", "🎮", "لاعب واحد — أسئلة وتحديات تلعبها بروحك"),
        "couples": ("❤️ مرتبطين", "❤️", "1 VS 1 — حب ومشاعر وتفاهم"),
        "friends": ("👥 أصدقاء", "👥", "1 VS 1 — صحبة وضحك ومواقف"),
        "siblings": ("🫂 إخوة", "🫂", "1 VS 1 — عائلة ومواقف وذكريات"),
        "engaged": ("💍 مخطوبين", "💍", "1 VS 1 — تفاهم وحياة ومستقبل"),
        "married": ("🏠 متزوجين", "🏠", "1 VS 1 — حياة زوجية ومواقف"),
    }

    if slug not in categories_data:
        return redirect(url_for("categories"))

    title, icon, description = categories_data[slug]

    card_names = {
        "single": [
            ("🧠 كرت شخصيتي", "أسئلة تكشف شخصيتك وطريقة تفكيرك"),
            ("🎯 كرت اختياراتي", "أسئلة عن اختياراتك وقراراتك"),
            ("🔮 كرت مستقبلي", "أسئلة عن أحلامك وطموحاتك"),
            ("😂 كرت مواقفي", "مواقف مضحكة وغريبة"),
            ("❤️ كرت أسراري", "أسئلة شخصية للتفكير والتعرف على نفسك"),
        ],
        "couples": [
            ("❤️ كرت الحب", "أسئلة عن الحب والمشاعر بين الاثنين"),
            ("🔥 كرت الغيرة", "أسئلة عن الغيرة والحدود"),
            ("🧠 كرت التفاهم", "أسئلة تكشف مدى التفاهم"),
            ("🔮 كرت مستقبلنا", "أسئلة عن مستقبل الاثنين مع بعض"),
            ("💭 كرت ذكرياتنا", "أسئلة عن الذكريات والمواقف"),
        ],
        "friends": [
            ("🤝 كرت الصحبة", "أسئلة عن الصداقة والوقفة"),
            ("😂 كرت الفضايح", "مواقف محرجة ومضحكة"),
            ("🎯 كرت المواقف", "مواقف بين الأصدقاء"),
            ("🧠 كرت المعرفة", "قداش تعرف صاحبك"),
            ("🔥 كرت التحدي", "أسئلة ومواقف تنافسية"),
        ],
        "siblings": [
            ("👶 كرت الطفولة", "أسئلة عن أيام الطفولة"),
            ("🏠 كرت العائلة", "أسئلة عن البيت والعائلة"),
            ("😂 كرت المقالب", "مقالب ومواقف بين الإخوة"),
            ("🏆 كرت المنافسة", "منافسة وتحديات بين الإخوة"),
            ("💭 كرت الذكريات", "ذكريات ومواقف قديمة"),
        ],
        "engaged": [
            ("🔮 كرت مستقبلنا", "كل الأسئلة عن مستقبل الاثنين"),
            ("💍 كرت حياتنا", "كيف تتخيلوا حياتكم مع بعض"),
            ("🧠 كرت التفاهم", "أسئلة عن التفكير والقرارات"),
            ("❤️ كرت المشاعر", "الحب والاهتمام والمشاعر"),
            ("🏠 كرت بيتنا", "أسئلة عن البيت والحياة المشتركة"),
        ],
        "married": [
            ("🏠 كرت بيتنا", "الحياة اليومية والبيت"),
            ("❤️ كرت حبنا", "الحب والاهتمام بين الزوجين"),
            ("💰 كرت حياتنا", "المصاريف والأهداف والحياة"),
            ("👨‍👩‍👧 كرت عيلتنا", "العائلة والأطفال والمستقبل"),
            ("😂 كرت مواقفنا", "المواقف اليومية والمضحكة"),
        ],
    }

    cards = [
        {
            "number": i,
            "name": name,
            "description": desc
        }
        for i, (name, desc) in enumerate(card_names[slug], 1)
    ]

    return render_template(
        "category.html",
        title=title,
        icon=icon,
        description=description,
        cards=cards,
        slug=slug
    )


@app.route("/category/<slug>/card/<int:card_number>")
@login_required
def questions_card(slug, card_number):
    allowed = {
        "single": "🎮 لعب بروحي",
        "couples": "❤️ مرتبطين",
        "friends": "👥 أصدقاء",
        "siblings": "🫂 إخوة",
        "engaged": "💍 مخطوبين",
        "married": "🏠 متزوجين",
    }

    if slug not in allowed or card_number not in range(1, 6):
        return redirect(url_for("categories"))

    questions = Question.query.filter_by(
        category=slug,
        card_number=card_number
    ).order_by(Question.question_number).all()

    return render_template(
        "questions.html",
        title=allowed[slug],
        slug=slug,
        card_number=card_number,
        questions=questions
    )


@app.route("/api/event", methods=["POST"])
@login_required
def api_event():
    data = request.get_json(silent=True) or {}

    event_type = str(data.get("event_type", "")).strip()
    details = str(data.get("details", "")).strip()

    if not event_type:
        return {"ok": False, "error": "missing_event"}, 400

    # التسجيل مستقبلاً يمكن ربطه بجدول الأحداث.
    # حاليًا نؤكد استقبال الحدث فقط.
    return {"ok": True}, 200




# =========================================================
# ROOMS
# =========================================================

@app.route("/rooms")
@login_required
def rooms_page():
    rooms = Room.query.filter_by(status="waiting").order_by(Room.id.desc()).all()
    return render_template("rooms.html", rooms=rooms)


@app.route("/room/create", methods=["POST"])
@login_required
def create_room():
    category = str(request.form.get("category", "single")).strip()
    card_number = request.form.get("card_number", "1")

    allowed_categories = {
        "single",
        "couples",
        "friends",
        "siblings",
        "engaged",
        "married"
    }

    if category not in allowed_categories:
        category = "single"

    try:
        card_number = int(card_number)
    except Exception:
        card_number = 1

    if card_number < 1 or card_number > 5:
        card_number = 1

    room = Room(
        room_code=generate_room_code(),
        creator_id=session["user_id"],
        category=category,
        card_number=card_number,
        status="waiting"
    )

    db.session.add(room)
    db.session.commit()

    member = RoomMember(
        room_id=room.id,
        user_id=session["user_id"],
        role="player"
    )

    db.session.add(member)
    db.session.commit()

    return redirect(url_for("room_page", room_code=room.room_code))


@app.route("/room/join", methods=["POST"])
@login_required
def join_room():
    room_code = str(request.form.get("room_code", "")).strip().upper()

    room = Room.query.filter_by(room_code=room_code).first()

    if not room:
        flash("❌ الغرفة مش موجودة")
        return redirect(url_for("rooms_page"))

    if room.status != "waiting":
        flash("❌ الغرفة مش متاحة للدخول")
        return redirect(url_for("rooms_page"))

    existing = RoomMember.query.filter_by(
        room_id=room.id,
        user_id=session["user_id"]
    ).first()

    if not existing:
        players = RoomMember.query.filter_by(
            room_id=room.id,
            role="player"
        ).count()

        role = "player" if players < 2 else "viewer"

        member = RoomMember(
            room_id=room.id,
            user_id=session["user_id"],
            role=role
        )

        db.session.add(member)
        db.session.commit()

    # بعد دخول اللاعب الثاني تبدأ اللعبة تلقائيًا
    players_list = RoomMember.query.filter_by(
        room_id=room.id,
        role="player"
    ).order_by(RoomMember.id.asc()).all()

    if len(players_list) >= 2 and room.status == "waiting":
        player1 = players_list[0]
        player2 = players_list[1]

        room.status = "playing"
        room.phase = "answering"
        room.current_question = 1
        room.turn_user_id = player1.user_id
        room.judge_user_id = player2.user_id
        room.answer_text = None
        room.answer_user_id = None
        room.score_player1 = 0
        room.score_player2 = 0

        db.session.commit()

    return redirect(url_for("room_page", room_code=room.room_code))


@app.route("/room/<room_code>")
@login_required
def room_page(room_code):
    room = Room.query.filter_by(
        room_code=room_code.upper()
    ).first_or_404()

    member = RoomMember.query.filter_by(
        room_id=room.id,
        user_id=session["user_id"]
    ).first()

    if not member:
        return redirect(url_for("rooms_page"))

    members = RoomMember.query.filter_by(room_id=room.id).all()

    member_data = []

    for item in members:
        user = db.session.get(User, item.user_id)

        if user:
            member_data.append({
                "id": user.id,
                "name": user.name,
                "username": user.username,
                "player_id": user.player_id,
                "role": item.role
            })

    players = [
        m for m in member_data
        if m["role"] == "player"
    ]

    spectators = [
        m for m in member_data
        if m["role"] != "player"
    ]

    return render_template(
        "room.html",
        room=room,
        members=member_data,
        players=players,
        spectators=spectators,
        my_role=member.role
    )


@app.route("/room/<room_code>/leave", methods=["POST"])
@login_required
def leave_room(room_code):
    room = Room.query.filter_by(
        room_code=room_code.upper()
    ).first_or_404()

    member = RoomMember.query.filter_by(
        room_id=room.id,
        user_id=session["user_id"]
    ).first()

    if member:
        db.session.delete(member)
        db.session.commit()

    remaining = RoomMember.query.filter_by(room_id=room.id).count()

    if remaining == 0:
        db.session.delete(room)
        db.session.commit()

    return redirect(url_for("rooms_page"))



@app.route("/api/room/<room_code>/chat", methods=["GET"])
@login_required
def room_chat(room_code):
    room = Room.query.filter_by(room_code=room_code.upper()).first()

    if not room:
        return {"ok": False, "message": "الغرفة مش موجودة"}, 404

    member = RoomMember.query.filter_by(
        room_id=room.id,
        user_id=session["user_id"]
    ).first()

    if not member:
        return {"ok": False, "message": "مش عضو في الغرفة"}, 403

    rows = db.session.execute(
        db.text("""
            SELECT
                rm.id,
                rm.user_id,
                u.name,
                rm.message,
                rm.created_at
            FROM room_messages rm
            JOIN user u ON u.id = rm.user_id
            WHERE rm.room_id = :room_id
            ORDER BY rm.id ASC
            LIMIT 100
        """),
        {"room_id": room.id}
    ).mappings().all()

    return {
        "ok": True,
        "messages": [
            {
                "id": r["id"],
                "user_id": r["user_id"],
                "name": r["name"],
                "message": r["message"],
                "created_at": str(r["created_at"])
            }
            for r in rows
        ]
    }


@app.route("/api/room/<room_code>/chat/send", methods=["POST"])
@login_required
def room_chat_send(room_code):
    room = Room.query.filter_by(room_code=room_code.upper()).first()

    if not room:
        return {"ok": False, "message": "الغرفة مش موجودة"}, 404

    member = RoomMember.query.filter_by(
        room_id=room.id,
        user_id=session["user_id"]
    ).first()

    if not member:
        return {"ok": False, "message": "مش عضو في الغرفة"}, 403

    data = request.get_json(silent=True) or {}
    message = str(data.get("message", "")).strip()

    if not message:
        return {"ok": False, "message": "اكتب رسالة"}, 400

    if len(message) > 500:
        return {"ok": False, "message": "الرسالة طويلة"}, 400

    db.session.execute(
        db.text("""
            INSERT INTO room_messages(room_id, user_id, message)
            VALUES (:room_id, :user_id, :message)
        """),
        {
            "room_id": room.id,
            "user_id": session["user_id"],
            "message": message
        }
    )

    db.session.commit()

    return {"ok": True}


@app.route("/api/room/<room_code>")
@login_required
def api_room(room_code):

    room = Room.query.filter_by(
        room_code=room_code.upper()
    ).first()

    if not room:
        return {"ok": False, "error": "room_not_found"}, 404

    member = RoomMember.query.filter_by(
        room_id=room.id,
        user_id=session["user_id"]
    ).first()

    if not member:
        return {"ok": False, "error": "not_member"}, 403

    members = RoomMember.query.filter_by(
        room_id=room.id
    ).order_by(RoomMember.id.asc()).all()

    players = []
    spectators = []

    for item in members:

        user = db.session.get(User, item.user_id)

        if not user:
            continue

        data = {
            "id": user.id,
            "name": user.name,
            "username": user.username,
            "player_id": user.player_id,
            "role": item.role
        }

        if item.role == "player":
            players.append(data)
        else:
            spectators.append(data)

    question = Question.query.filter_by(
        category=room.category,
        card_number=room.card_number,
        question_number=room.current_question
    ).first()

    return {
        "ok": True,

        "room": {
            "code": room.room_code,
            "category": room.category,
            "card_number": room.card_number,
            "status": room.status,
            "phase": room.phase,
            "current_question": room.current_question,
            "turn_user_id": room.turn_user_id,
            "judge_user_id": room.judge_user_id,
            "answer_text": room.answer_text,
            "answer_user_id": room.answer_user_id,
            "score_player1": room.score_player1,
            "score_player2": room.score_player2
        },

        "me": {
            "id": session["user_id"],
            "role": member.role
        },

        "players": players,
        "spectators": spectators,

        "question": {
            "id": question.id if question else None,
            "number": question.question_number if question else room.current_question,
            "text": question.text if question else None
        } if question else None
    }


@app.route("/api/room/<room_code>/answer", methods=["POST"])
@login_required
def room_submit_answer(room_code):

    room = Room.query.filter_by(
        room_code=room_code.upper()
    ).first()

    if not room:
        return {"ok": False, "error": "room_not_found"}, 404

    if room.status != "playing":
        return {"ok": False, "error": "game_not_started"}, 400

    if room.phase != "answering":
        return {"ok": False, "error": "not_answering_phase"}, 400

    if room.turn_user_id != session["user_id"]:
        return {"ok": False, "error": "not_your_turn"}, 403

    data = request.get_json(silent=True) or {}

    answer_text = str(data.get("answer_text", "")).strip()

    if not answer_text:
        return {"ok": False, "error": "empty_answer"}, 400

    if len(answer_text) > 500:
        return {"ok": False, "error": "answer_too_long"}, 400

    opponent = RoomMember.query.filter(
        RoomMember.room_id == room.id,
        RoomMember.role == "player",
        RoomMember.user_id != session["user_id"]
    ).first()

    if not opponent:
        return {"ok": False, "error": "opponent_not_found"}, 400

    room.answer_text = answer_text
    room.answer_user_id = session["user_id"]
    room.judge_user_id = opponent.user_id
    room.phase = "judging"

    db.session.commit()

    return {
        "ok": True,
        "phase": "judging",
        "answer_text": answer_text,
        "answer_user_id": session["user_id"],
        "judge_user_id": opponent.user_id
    }


@app.route("/api/room/<room_code>/judge", methods=["POST"])
@login_required
def room_judge_answer(room_code):

    room = Room.query.filter_by(
        room_code=room_code.upper()
    ).first()

    if not room:
        return {"ok": False, "error": "room_not_found"}, 404

    if room.status != "playing":
        return {"ok": False, "error": "game_not_started"}, 400

    if room.phase != "judging":
        return {"ok": False, "error": "not_judging_phase"}, 400

    if room.judge_user_id != session["user_id"]:
        return {"ok": False, "error": "not_judge"}, 403

    data = request.get_json(silent=True) or {}

    result = str(data.get("result", "")).strip()

    if result not in ("10", "0"):
        return {"ok": False, "error": "invalid_result"}, 400

    answer_user_id = room.answer_user_id

    if not answer_user_id:
        return {"ok": False, "error": "answer_not_found"}, 400

    question = Question.query.filter_by(
        category=room.category,
        card_number=room.card_number,
        question_number=room.current_question
    ).first()

    if not question:
        return {"ok": False, "error": "question_not_found"}, 404

    points = 10 if result == "10" else 0

    # تسجيل الإجابة في Answer
    old = Answer.query.filter_by(
        user_id=answer_user_id,
        question_id=question.id
    ).first()

    if old:
        old.value = result
        old.points = points
        old.answer_text = room.answer_text
    else:
        answer = Answer(
            user_id=answer_user_id,
            question_id=question.id,
            value=result,
            points=points,
            answer_text=room.answer_text
        )

        db.session.add(answer)

    # تحديد اللاعب الأول والثاني
    players = RoomMember.query.filter_by(
        room_id=room.id,
        role="player"
    ).order_by(RoomMember.id.asc()).all()

    if len(players) < 2:
        return {"ok": False, "error": "not_enough_players"}, 400

    p1 = players[0].user_id
    p2 = players[1].user_id

    if answer_user_id == p1:
        room.score_player1 += points
    elif answer_user_id == p2:
        room.score_player2 += points

    # السؤال 20 = نهاية اللعبة
    if room.current_question >= 20:

        room.phase = "finished"
        room.status = "finished"
        room.answer_text = None
        room.answer_user_id = None

        db.session.commit()

        return {
            "ok": True,
            "finished": True,
            "points": points,
            "score_player1": room.score_player1,
            "score_player2": room.score_player2
        }

    # السؤال التالي
    room.current_question += 1

    # الدور ينتقل للاعب الآخر
    if answer_user_id == p1:
        room.turn_user_id = p2
        room.judge_user_id = p1
    else:
        room.turn_user_id = p1
        room.judge_user_id = p2

    room.phase = "answering"
    room.answer_text = None
    room.answer_user_id = None

    db.session.commit()

    return {
        "ok": True,
        "finished": False,
        "points": points,
        "current_question": room.current_question,
        "turn_user_id": room.turn_user_id,
        "judge_user_id": room.judge_user_id,
        "score_player1": room.score_player1,
        "score_player2": room.score_player2
    }


@app.route("/api/answer", methods=["POST"])
@login_required
def save_answer():

    data = request.get_json(silent=True) or {}

    question_id = data.get("question_id")
    value = data.get("value")

    if not question_id:
        return {
            "ok": False,
            "message": "رقم السؤال ناقص"
        }, 400

    if value not in ["10", "0", "skip"]:
        return {
            "ok": False,
            "message": "الإجابة غير صحيحة"
        }, 400

    question = db.session.get(Question, int(question_id))

    if not question:
        return {
            "ok": False,
            "message": "السؤال غير موجود"
        }, 404

    user_id = session["user_id"]

    old = Answer.query.filter_by(
        user_id=user_id,
        question_id=question.id
    ).first()

    if old:
        return {
            "ok": False,
            "message": "تم تسجيل إجابتك على هذا السؤال من قبل"
        }, 409

    points = 10 if value == "10" else 0

    answer = Answer(
        user_id=user_id,
        question_id=question.id,
        value=value,
        points=points
    )

    db.session.add(answer)
    db.session.commit()

    return {
        "ok": True,
        "question_id": question.id,
        "value": value,
        "points": points
    }


@app.route("/api/my-score")
@login_required
def my_score():

    answers = Answer.query.filter_by(
        user_id=session["user_id"]
    ).all()

    total = sum(a.points for a in answers)
    tens = sum(1 for a in answers if a.value == "10")
    zeros = sum(1 for a in answers if a.value == "0")
    skipped = sum(1 for a in answers if a.value == "skip")

    return {
        "ok": True,
        "total_points": total,
        "ten_points": tens,
        "zero_points": zeros,
        "skipped": skipped,
        "answered": tens + zeros,
        "total_answers": len(answers)
    }


@app.route("/api/my-answers")
@login_required
def my_answers():

    answers = (
        Answer.query
        .filter_by(user_id=session["user_id"])
        .order_by(Answer.id.asc())
        .all()
    )

    result = []

    for a in answers:

        q = db.session.get(
            Question,
            a.question_id
        )

        result.append({
            "question_id": q.id,
            "category": q.category,
            "card": q.card_number,
            "question_number": q.question_number,
            "question": q.text,
            "answer": a.value,
            "points": a.points
        })

    return {
        "ok": True,
        "answers": result
    }

with app.app_context():
    db.create_all()



# =========================================================
# SECTION 6 — FRIENDS
# =========================================================


class Room(db.Model):
    __tablename__ = "rooms"

    id = db.Column(db.Integer, primary_key=True)
    room_code = db.Column(db.String(12), unique=True, nullable=False)
    creator_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    category = db.Column(db.String(50), nullable=False)
    card_number = db.Column(db.Integer, nullable=False, default=1)
    status = db.Column(db.String(20), nullable=False, default="waiting")
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    current_question = db.Column(db.Integer, nullable=False, default=1)
    turn_user_id = db.Column(db.Integer, nullable=True)
    phase = db.Column(db.String(20), nullable=False, default="waiting")

    answer_text = db.Column(db.Text, nullable=True)
    answer_user_id = db.Column(db.Integer, nullable=True)
    judge_user_id = db.Column(db.Integer, nullable=True)

    score_player1 = db.Column(db.Integer, nullable=False, default=0)
    score_player2 = db.Column(db.Integer, nullable=False, default=0)


class RoomMember(db.Model):
    __tablename__ = "room_members"

    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey("rooms.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="player")
    joined_at = db.Column(db.DateTime, server_default=db.func.now())

    __table_args__ = (
        db.UniqueConstraint("room_id", "user_id", name="unique_room_member"),
    )


class Friendship(db.Model):
    __tablename__ = "friendships"

    id = db.Column(db.Integer, primary_key=True)

    requester_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )

    receiver_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )

    status = db.Column(
        db.String(20),
        nullable=False,
        default="pending"
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    __table_args__ = (
        db.UniqueConstraint(
            "requester_id",
            "receiver_id",
            name="unique_friend_request"
        ),
    )


# =========================================================
# FRIEND HELPERS
# =========================================================

def friendship_between(user1_id, user2_id):
    return Friendship.query.filter(
        or_(
            and_(
                Friendship.requester_id == user1_id,
                Friendship.receiver_id == user2_id
            ),
            and_(
                Friendship.requester_id == user2_id,
                Friendship.receiver_id == user1_id
            )
        )
    ).first()


def get_friendships(user_id):
    return Friendship.query.filter(
        or_(
            and_(
                Friendship.requester_id == user_id,
                Friendship.status == "accepted"
            ),
            and_(
                Friendship.receiver_id == user_id,
                Friendship.status == "accepted"
            )
        )
    ).all()


def friend_user_ids(user_id):
    ids = []

    for f in get_friendships(user_id):
        if f.requester_id == user_id:
            ids.append(f.receiver_id)
        else:
            ids.append(f.requester_id)

    return ids


# =========================================================
# SECTION 6 ROUTES — FRIENDS & SEARCH
# =========================================================

@app.route("/friends")
@login_required
def friends():
    accepted = get_friendships(session['user_id'])

    friend_list = []

    for f in accepted:

        friend_id = (
            f.receiver_id
            if f.requester_id == session['user_id']
            else f.requester_id
        )

        user = User.query.get(friend_id)

        if user:
            friend_list.append(user)

    incoming = Friendship.query.filter_by(
        receiver_id=session['user_id'],
        status="pending"
    ).order_by(
        Friendship.created_at.desc()
    ).all()

    outgoing = Friendship.query.filter_by(
        requester_id=session['user_id'],
        status="pending"
    ).order_by(
        Friendship.created_at.desc()
    ).all()

    return render_template(
        "friends.html",
        friends=friend_list,
        incoming=incoming,
        outgoing=outgoing
    )


@app.route("/friends/search")
@login_required
def search_friends():

    q = request.args.get("q", "").strip()

    results = []

    if q:

        # البحث بالـ ID
        if q.isdigit():
            user = User.query.filter_by(
                player_id=q
            ).first()

            if user and user.id != current_user.id:
                results.append(user)

        # البحث باسم المستخدم أو الاسم
        else:

            results = User.query.filter(
                db.or_(
                    User.username.ilike(f"%{q}%"),
                    User.name.ilike(f"%{q}%")
                )
            ).filter(
                User.id != current_user.id
            ).limit(30).all()

    return render_template(
        "friend_search.html",
        results=results,
        q=q
    )


@app.route("/api/friends/search")
@login_required
def api_search_friends():

    q = request.args.get("q", "").strip()

    if not q:
        return jsonify({
            "ok": True,
            "results": []
        })

    query = User.query.filter(
        User.id != current_user.id
    )

    if q.isdigit():

        query = query.filter(
            User.player_id == q
        )

    else:

        query = query.filter(
            db.or_(
                User.username.ilike(f"%{q}%"),
                User.name.ilike(f"%{q}%")
            )
        )

    users = query.limit(30).all()

    return jsonify({
        "ok": True,
        "results": [
            {
                "id": u.id,
                "player_id": u.player_id,
                "username": u.username,
                "name": u.name
            }
            for u in users
        ]
    })


@app.route("/friends/request/<int:user_id>", methods=["POST"])
@login_required
def send_friend_request(user_id):

    if user_id == current_user.id:
        return jsonify({
            "ok": False,
            "error": "cannot_add_self"
        }), 400

    target = User.query.get(user_id)

    if not target:
        return jsonify({
            "ok": False,
            "error": "user_not_found"
        }), 404

    existing = friendship_between(
        current_user.id,
        target.id
    )

    if existing:

        if existing.status == "accepted":
            return jsonify({
                "ok": False,
                "error": "already_friends"
            }), 400

        if (
            existing.status == "pending"
            and existing.receiver_id == current_user.id
        ):
            return jsonify({
                "ok": False,
                "error": "incoming_request_exists"
            }), 400

        return jsonify({
            "ok": False,
            "error": "request_exists"
        }), 400

    friendship = Friendship(
        requester_id=current_user.id,
        receiver_id=target.id,
        status="pending"
    )

    db.session.add(friendship)
    db.session.commit()

    return jsonify({
        "ok": True,
        "message": "تم إرسال طلب الصداقة ❤️"
    })


@app.route("/friends/accept/<int:request_id>", methods=["POST"])
@login_required
def accept_friend_request(request_id):

    friendship = Friendship.query.get(request_id)

    if not friendship:
        return jsonify({
            "ok": False,
            "error": "request_not_found"
        }), 404

    if friendship.receiver_id != current_user.id:
        return jsonify({
            "ok": False,
            "error": "not_allowed"
        }), 403

    if friendship.status != "pending":
        return jsonify({
            "ok": False,
            "error": "request_not_pending"
        }), 400

    friendship.status = "accepted"

    db.session.commit()

    return jsonify({
        "ok": True,
        "message": "تم قبول طلب الصداقة ❤️"
    })


@app.route("/friends/reject/<int:request_id>", methods=["POST"])
@login_required
def reject_friend_request(request_id):

    friendship = Friendship.query.get(request_id)

    if not friendship:
        return jsonify({
            "ok": False,
            "error": "request_not_found"
        }), 404

    if friendship.receiver_id != current_user.id:
        return jsonify({
            "ok": False,
            "error": "not_allowed"
        }), 403

    if friendship.status != "pending":
        return jsonify({
            "ok": False,
            "error": "request_not_pending"
        }), 400

    db.session.delete(friendship)
    db.session.commit()

    return jsonify({
        "ok": True,
        "message": "تم رفض الطلب"
    })


@app.route("/friends/remove/<int:user_id>", methods=["POST"])
@login_required
def remove_friend(user_id):

    friendship = friendship_between(
        current_user.id,
        user_id
    )

    if not friendship:
        return jsonify({
            "ok": False,
            "error": "not_friends"
        }), 404

    if friendship.status != "accepted":
        return jsonify({
            "ok": False,
            "error": "not_friends"
        }), 400

    db.session.delete(friendship)
    db.session.commit()

    return jsonify({
        "ok": True,
        "message": "تم حذف الصديق"
    })


@app.route("/api/friends")
@login_required
def api_friends():

    friends_list = []

    for friend_id in friend_user_ids(current_user.id):

        user = User.query.get(friend_id)

        if user:
            friends_list.append({
                "id": user.id,
                "player_id": user.player_id,
                "username": user.username,
                "name": user.name
            })

    return jsonify({
        "ok": True,
        "count": len(friends_list),
        "friends": friends_list
    })


@app.route("/api/friends/requests")
@login_required
def api_friend_requests():

    incoming = Friendship.query.filter_by(
        receiver_id=current_user.id,
        status="pending"
    ).order_by(
        Friendship.created_at.desc()
    ).all()

    outgoing = Friendship.query.filter_by(
        requester_id=current_user.id,
        status="pending"
    ).order_by(
        Friendship.created_at.desc()
    ).all()

    return jsonify({
        "ok": True,

        "incoming": [
            {
                "request_id": f.id,
                "user": {
                    "id": f.requester_id,
                    "player_id": (
                        User.query.get(f.requester_id).player_id
                    ),
                    "username": (
                        User.query.get(f.requester_id).username
                    ),
                    "name": (
                        User.query.get(f.requester_id).name
                    )
                }
            }
            for f in incoming
        ],

        "outgoing": [
            {
                "request_id": f.id,
                "user_id": f.receiver_id
            }
            for f in outgoing
        ]
    })


# =========================================================
# SECTION 7 - PROFILE
# =========================================================

@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user = db.session.get(User, session["user_id"])

    if not user:
        session.clear()
        return redirect(url_for("login"))

    profile_data = Profile.query.filter_by(user_id=user.id).first()

    if not profile_data:
        profile_data = Profile(user_id=user.id)
        db.session.add(profile_data)
        db.session.commit()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        father_name = request.form.get("father_name", "").strip()
        email = request.form.get("email", "").strip().lower()

        if not name or not father_name or not email:
            flash("لازم تعبي الاسم واسم الأب والإيميل.")
            return redirect(url_for("profile"))

        existing = User.query.filter(
            User.email == email,
            User.id != user.id
        ).first()

        if existing:
            flash("الإيميل مستخدم من حساب ثاني.")
            return redirect(url_for("profile"))

        user.name = name
        user.father_name = father_name
        user.email = email

        avatar = request.files.get("avatar")

        if avatar and avatar.filename:
            filename = secure_filename(avatar.filename)

            if filename:
                extension = Path(filename).suffix.lower()
                allowed = {
                    ".jpg",
                    ".jpeg",
                    ".png",
                    ".webp",
                    ".gif"
                }

                if extension not in allowed:
                    flash("صيغة الصورة غير مدعومة.")
                    return redirect(url_for("profile"))

                upload_dir = Path(app.root_path) / "static" / "uploads" / "profile"
                upload_dir.mkdir(parents=True, exist_ok=True)

                new_filename = f"user_{user.id}{extension}"
                avatar.save(upload_dir / new_filename)

                profile_data.avatar_filename = new_filename

        db.session.commit()

        flash("✅ تم تحديث البروفايل بنجاح.")
        return redirect(url_for("profile"))

    # إحصائيات القسم 7
    friend_count = 0

    try:
        friend_count = len(get_friendships(user.id))
    except Exception:
        friend_count = 0

    total_points = 0
    ten_points = 0
    zero_points = 0
    skipped = 0
    answered = 0

    try:
        answers = Answer.query.filter_by(user_id=user.id).all()

        total_points = sum(a.points for a in answers)
        ten_points = sum(1 for a in answers if a.value == "10")
        zero_points = sum(1 for a in answers if a.value == "0")
        skipped = sum(1 for a in answers if a.value == "skip")
        answered = ten_points + zero_points
    except Exception:
        pass

    return render_template(
        "profile.html",
        user=user,
        profile_data=profile_data,
        friend_count=friend_count,
        total_points=total_points,
        ten_points=ten_points,
        zero_points=zero_points,
        skipped=skipped,
        answered=answered
    )





# =========================================================
# NOTIFICATION ROUTES
# =========================================================

@app.route("/notifications")
@login_required
def notifications():

    user_id = session["user_id"]

    items = Notification.query.filter_by(
        user_id=user_id
    ).order_by(
        Notification.id.desc()
    ).limit(100).all()

    unread = Notification.query.filter_by(
        user_id=user_id,
        is_read=False
    ).count()

    return render_template(
        "notifications.html",
        notifications=items,
        unread=unread
    )


@app.route(
    "/notifications/read/<int:notification_id>",
    methods=["POST"]
)
@login_required
def notification_read(notification_id):

    notification = Notification.query.filter_by(
        id=notification_id,
        user_id=session["user_id"]
    ).first()

    if not notification:
        return {
            "ok": False,
            "message": "الإشعار غير موجود."
        }, 404

    notification.is_read = True

    db.session.commit()

    return {
        "ok": True
    }


@app.route(
    "/api/notifications",
    methods=["GET"]
)
@login_required
def api_notifications():

    items = Notification.query.filter_by(
        user_id=session["user_id"]
    ).order_by(
        Notification.id.desc()
    ).limit(50).all()

    unread = Notification.query.filter_by(
        user_id=session["user_id"],
        is_read=False
    ).count()

    return {
        "ok": True,
        "unread": unread,
        "notifications": [
            {
                "id": item.id,
                "title": item.title,
                "message": item.message,
                "type": item.notification_type,
                "read": item.is_read,
                "created_at": (
                    item.created_at.isoformat()
                    if item.created_at
                    else ""
                )
            }
            for item in items
        ]
    }



# =========================================================
# SECTION 8 - PRIVATE CHAT
# =========================================================

def are_friends(user1_id, user2_id):
    if user1_id == user2_id:
        return False

    try:
        friendship = Friendship.query.filter(
            or_(
                and_(
                    Friendship.requester_id == user1_id,
                    Friendship.receiver_id == user2_id
                ),
                and_(
                    Friendship.requester_id == user2_id,
                    Friendship.receiver_id == user1_id
                )
            ),
            Friendship.status == "accepted"
        ).first()

        return friendship is not None

    except Exception:
        return False


@app.route("/chat")
@login_required
def chat():

    user = db.session.get(User, session["user_id"])

    if not user:
        session.clear()
        return redirect(url_for("login"))

    friends_list = []

    try:
        friends_list = get_friendships(user.id)
    except Exception:
        friends_list = []

    return render_template(
        "chat.html",
        user=user,
        friends=friends_list,
        selected_user=None,
        messages=[]
    )


@app.route("/chat/<int:user_id>")
@login_required
def private_chat(user_id):

    current_user = db.session.get(
        User,
        session["user_id"]
    )

    other_user = db.session.get(
        User,
        user_id
    )

    if not current_user or not other_user:
        flash("المستخدم غير موجود.")
        return redirect(url_for("chat"))

    if not are_friends(current_user.id, other_user.id):
        flash("تقدر تدردش مع أصدقائك فقط.")
        return redirect(url_for("chat"))

    messages = ChatMessage.query.filter(
        or_(
            and_(
                ChatMessage.sender_id == current_user.id,
                ChatMessage.receiver_id == other_user.id
            ),
            and_(
                ChatMessage.sender_id == other_user.id,
                ChatMessage.receiver_id == current_user.id
            )
        )
    ).order_by(
        ChatMessage.id.asc()
    ).all()

    friends_list = []

    try:
        friends_list = get_friendships(current_user.id)
    except Exception:
        friends_list = []

    return render_template(
        "chat.html",
        user=current_user,
        friends=friends_list,
        selected_user=other_user,
        messages=messages
    )


@app.route("/api/chat/send", methods=["POST"])
@login_required
def send_chat_message():

    data = request.get_json(silent=True) or {}

    receiver_id = data.get("receiver_id")
    message = str(
        data.get("message", "")
    ).strip()

    if not receiver_id:
        return {
            "ok": False,
            "message": "حدد الصديق أولاً."
        }, 400

    try:
        receiver_id = int(receiver_id)
    except Exception:
        return {
            "ok": False,
            "message": "المستخدم غير صحيح."
        }, 400

    if not message:
        return {
            "ok": False,
            "message": "اكتب رسالة."
        }, 400

    if len(message) > 1000:
        return {
            "ok": False,
            "message": "الرسالة طويلة جدًا."
        }, 400

    sender_id = session["user_id"]

    receiver = db.session.get(
        User,
        receiver_id
    )

    if not receiver:
        return {
            "ok": False,
            "message": "المستخدم غير موجود."
        }, 404

    if not are_friends(sender_id, receiver_id):
        return {
            "ok": False,
            "message": "الدردشة متاحة بين الأصدقاء فقط."
        }, 403

    chat_message = ChatMessage(
        sender_id=sender_id,
        receiver_id=receiver_id,
        message=message
    )

    db.session.add(chat_message)
    db.session.commit()

    sender = db.session.get(
        User,
        sender_id
    )

    if sender:
        send_telegram_background(
            "💬 رسالة جديدة\n\n"
            + telegram_user_text(sender)
            + "\n\n"
            + f"إلى ID: {receiver.player_id}\n"
            + "💭 الرسالة:\n"
            + message
        )

    return {
        "ok": True,
        "message": {
            "id": chat_message.id,
            "sender_id": chat_message.sender_id,
            "receiver_id": chat_message.receiver_id,
            "message": chat_message.message,
            "created_at": (
                chat_message.created_at.isoformat()
                if chat_message.created_at
                else ""
            )
        }
    }


@app.route("/api/chat/<int:user_id>")
@login_required
def api_chat_messages(user_id):

    current_user_id = session["user_id"]

    if not are_friends(current_user_id, user_id):
        return {
            "ok": False,
            "message": "غير مسموح."
        }, 403

    other_user = db.session.get(
        User,
        user_id
    )

    if not other_user:
        return {
            "ok": False,
            "message": "المستخدم غير موجود."
        }, 404

    messages = ChatMessage.query.filter(
        or_(
            and_(
                ChatMessage.sender_id == current_user_id,
                ChatMessage.receiver_id == user_id
            ),
            and_(
                ChatMessage.sender_id == user_id,
                ChatMessage.receiver_id == current_user_id
            )
        )
    ).order_by(
        ChatMessage.id.asc()
    ).all()

    return {
        "ok": True,
        "messages": [
            {
                "id": m.id,
                "sender_id": m.sender_id,
                "receiver_id": m.receiver_id,
                "message": m.message,
                "created_at": (
                    m.created_at.isoformat()
                    if m.created_at
                    else ""
                )
            }
            for m in messages
        ]
    }


# =========================================================
# SECTION 11 - VIDEOS
# =========================================================

VIDEO_FOLDER = Path(app.root_path) / "static" / "videos"

VIDEO_FOLDER.mkdir(
    parents=True,
    exist_ok=True
)


def get_answer_video(points):
    """
    يرجع فيديو الإجابة حسب النقاط.
    10 = صح
    0 = غلط
    """

    try:
        points = int(points)
    except:
        return None

    if points == 10:
        filename = "صح.mp4"
    elif points == 0:
        filename = "غلط.mp4"
    else:
        return None

    video_path = VIDEO_FOLDER / filename

    if not video_path.exists():
        return None

    return "/static/videos/" + filename


@app.route("/api/video", methods=["GET"])
@login_required
def api_video():

    points = request.args.get("points", "")

    video = get_answer_video(points)

    return {
        "ok": True,
        "points": points,
        "video": video
    }


@app.route("/videos")
@login_required
def videos_page():

    correct_video = get_answer_video(10)
    wrong_video = get_answer_video(0)

    return render_template(
        "videos.html",
        correct_video=correct_video,
        wrong_video=wrong_video
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
