"""Public pages; authentication will be implemented separately."""

from flask import Blueprint, render_template

main = Blueprint("main", __name__)


@main.get("/")
def index():
    return render_template("index.html")


@main.get("/login")
def login():
    return render_template(
        "account.html", mode="login", title="Вход",
        heading="С возвращением в Times.",
        description="Вход в личный кабинет скоро появится. А пока читайте ленту — она открыта для всех.",
    )


@main.get("/register")
def register():
    return render_template(
        "account.html", mode="register", title="Регистрация",
        heading="Станьте частью редакции.",
        description="Регистрация скоро откроется. Вы сможете предлагать новости и рассказывать о жизни университета.",
    )


@main.get("/support")
def support():
    return render_template("support.html")
