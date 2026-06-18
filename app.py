"""
Hotel Schema Maker - Main Application Entry Point
A tool to generate JSON-LD schema and XML sitemaps for hotel websites.
"""

import os
from dotenv import load_dotenv
from flask import Flask
from flask_cors import CORS

load_dotenv()
from backend.auth import auth_bp
from backend.schema_routes import schema_bp
from backend.sitemap_routes import sitemap_bp
from backend.feed_routes import feed_bp
from backend.admin_routes import admin_bp
from backend.database import init_db

app = Flask(
    __name__,
    template_folder="frontend/templates",
    static_folder="frontend/static"
)

# Configuration
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "hotel-schema-maker-dev-key-change-in-prod")
app.config["DATABASE_URL"] = os.environ.get("DATABASE_URL", "sqlite:///hotel_schema.db")
app.config["SUPABASE_URL"] = os.environ.get("SUPABASE_URL", "")
app.config["SUPABASE_KEY"] = os.environ.get("SUPABASE_KEY", "")
app.config["JWT_SECRET"] = os.environ.get("JWT_SECRET", "jwt-secret-change-in-prod")

CORS(app, resources={r"/api/*": {"origins": "*"}})

# Register blueprints
app.register_blueprint(auth_bp, url_prefix="/api/auth")
app.register_blueprint(schema_bp, url_prefix="/api/schema")
app.register_blueprint(sitemap_bp, url_prefix="/api/sitemap")
app.register_blueprint(feed_bp, url_prefix="/api/feed")
app.register_blueprint(admin_bp, url_prefix="/api/admin")

# Serve frontend
from flask import render_template

@app.route("/")
@app.route("/<path:path>")
def index(path=""):
    return render_template("index.html")

# Initialize database on startup
with app.app_context():
    init_db(app)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV", "development") == "development"
    app.run(host="0.0.0.0", port=port, debug=debug)
