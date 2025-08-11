from flask import Blueprint, request, jsonify, render_template
from db import Album  # adjust import to your project structure
from app import db  # or your session object

bp = Blueprint("albums", __name__)

@bp.route("/albums/filter")
def filter_albums():
    search = request.args.get("search", "")
    sort = request.args.get("sort", "name")

    query = db.session.query(Album).filter(Album.name.ilike(f"%{search}%"))

    if sort == "release_date":
        query = query.order_by(Album.release_date.desc())
    elif sort == "popularity":
        query = query.order_by(Album.popularity.desc())
    else:
        query = query.order_by(Album.name.asc())

    albums = query.all()
    html = render_template("partials/album_list.html", albums=albums)
    return jsonify({"html": html})

@bp.route("/albums/details/<string:album_id>")
def album_details(album_id):
    album = db.session.get(Album, album_id)
    return render_template("partials/album_details.html", album=album)
