import os
import re
from typing import List, Optional
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import instaloader

# Inisialisasi aplikasi FastAPI
app = FastAPI(
    title="InstaSense Cloud Scraper API",
    description="Backend microservice untuk mengambil komentar Instagram dan menyajikannya ke dashboard analitik sentimen.",
    version="1.0.0"
)

# Konfigurasi CORS: Mengizinkan request dari aplikasi mobile (Android/iOS/Capacitor) & Web
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Konfigurasi Instaloader (hanya metadata komentar, tanpa download media agar hemat bandwidth & memori)
loader = instaloader.Instaloader(
    download_pictures=False,
    download_videos=False,
    download_video_thumbnails=False,
    download_geotags=False,
    save_metadata=False,
    compress_history=False,
    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Opsi login otomatis jika username & password diset di Environment Variables Render
IG_USERNAME = os.getenv("IG_USERNAME")
IG_PASSWORD = os.getenv("IG_PASSWORD")
if IG_USERNAME and IG_PASSWORD:
    try:
        loader.login(IG_USERNAME, IG_PASSWORD)
        print("Berhasil login ke Instagram dummy account.")
    except Exception as e:
        print(f"Peringatan: Gagal login Instagram, beralih ke mode anonim: {e}")


class ScrapeRequest(BaseModel):
    url: str = Field(..., example="https://www.instagram.com/p/C7abcdefg/")
    max_comments: Optional[int] = Field(default=40, ge=5, le=150)


def extract_shortcode(input_url: str) -> str:
    """Ekstrak kode unik postingan Instagram dari URL Post, Reel, atau TV"""
    clean_url = input_url.strip()
    
    # Cek jika pengguna hanya memasukkan shortcode mentahnya
    if re.match(r"^[A-Za-z0-9_-]{10,12}$", clean_url):
        return clean_url
        
    pattern = r"(?:instagram\.com/(?:p|reel|tv)/)([\w-]+)"
    match = re.search(pattern, clean_url)
    if not match:
        raise ValueError("Format URL tidak valid. Gunakan format: https://www.instagram.com/p/SHORTCODE/ atau https://www.instagram.com/reel/SHORTCODE/")
    return match.group(1)


@app.get("/")
def home():
    """Health check endpoint untuk memverifikasi server aktif"""
    return {
        "status": "online",
        "service": "InstaSense Cloud Scraper API",
        "docs_url": "/docs"
    }


@app.post("/api/scrape-comments")
def scrape_comments(payload: ScrapeRequest):
    """
    Endpoint utama yang dipanggil oleh aplikasi mobile / dashboard web.
    Mengambil daftar komentar publik dari URL postingan yang diberikan.
    """
    try:
        shortcode = extract_shortcode(payload.url)
    except ValueError as ve:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(ve)
        )

    try:
        # Mengambil objek Post dari Instagram
        post = instaloader.Post.from_shortcode(loader.context, shortcode)
        
        extracted_comments = []
        limit = payload.max_comments

        # Iterasi komentar postingan
        for comment in post.get_comments():
            extracted_comments.append({
                "id": str(comment.id),
                "author": comment.owner.username,
                "text": comment.text.strip(),
                "likes": comment.likes_count,
                "created_at": comment.created_at_utc.isoformat()
            })
            
            if len(extracted_comments) >= limit:
                break

        return {
            "status": "success",
            "shortcode": shortcode,
            "owner_username": post.owner_username,
            "caption": (post.caption or "")[:200],  # Ringkasan caption
            "likes_count": post.likes,
            "total_fetched": len(extracted_comments),
            "comments": extracted_comments
        }

    except instaloader.exceptions.ProfileNotExistsException:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Postingan atau akun tidak ditemukan."
        )
    except instaloader.exceptions.PrivateHttpException:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Postingan berasal dari akun privat. Hanya postingan publik yang bisa di-scrape."
        )
    except instaloader.exceptions.ConnectionException as ce:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Instagram membatasi akses (Rate limit). Coba beberapa saat lagi atau gunakan akun login: {str(ce)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Terjadi kesalahan saat scraping: {str(e)}"
        )
