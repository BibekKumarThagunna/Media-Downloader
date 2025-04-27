# streamlit_app.py
import streamlit as st
import requests
import yt_dlp
import instaloader # Added instaloader
import os
import json
from urllib.parse import urlparse, unquote
from io import BytesIO
import tempfile
import re
import logging
import time # For potential delays

# Configure basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Utility Functions ---

def sanitize_filename(filename):
    """Removes or replaces characters invalid for typical filesystems."""
    sanitized = re.sub(r'[\\/*?:"<>|]', "_", filename) # Replace invalid chars with underscore
    sanitized = re.sub(r'\.+', '.', sanitized)
    sanitized = sanitized.strip().strip('.')
    if not sanitized:
        sanitized = "downloaded_file"
    # Limit length (common filesystem limit is 255, be conservative)
    max_len = 150
    if len(sanitized) > max_len:
         name, ext = os.path.splitext(sanitized)
         sanitized = name[:max_len - len(ext) - 1] + ext
    return sanitized

def display_download_button(file_data_bytes, filename, mime_type, status_placeholder):
     """Displays the download button and success message."""
     file_size_mb = len(file_data_bytes) / (1024 * 1024)
     # Ensure the placeholder is cleared before showing the button
     status_placeholder.empty()
     # Use columns to place button nicely if desired, or just place directly
     button_placeholder = st.empty()
     with button_placeholder:
          st.download_button(
              label=f"💾 Download File ({file_size_mb:.2f} MB)",
              data=file_data_bytes,
              file_name=filename,
              mime=mime_type
          )
     st.success(f"✅ Download Ready: {filename}")


# --- Instagram Downloader (Uses Instaloader) ---

def download_instagram(link, status_placeholder):
     """Attempts to download a public Instagram post/reel using Instaloader."""
     logging.info(f"Attempting Instagram download for: {link}")
     status_placeholder.info("📸 Connecting to Instagram (public posts only)...")

     match = re.search(r"(?:p|reel|tv)/([\w-]+)", link)
     if not match:
          st.error("❌ Invalid Instagram post/reel URL format.")
          status_placeholder.empty()
          return False
     shortcode = match.group(1)

     try:
          L = instaloader.Instaloader(
               download_pictures=True, download_videos=True, download_video_thumbnails=False,
               download_geotags=False, download_comments=False, save_metadata=False,
               compress_json=False, post_metadata_txt_pattern='', max_connection_attempts=3,
               request_timeout=15
          )
          # No login attempt - public only

          status_placeholder.info(f"🔎 Fetching Instagram post: {shortcode}...")
          post = instaloader.Post.from_shortcode(L.context, shortcode)

          is_video = post.is_video
          target_url = post.video_url if is_video else post.url

          if not target_url:
               st.error("❌ Could not find media URL in the Instagram post.")
               status_placeholder.empty()
               return False

          owner = post.owner_username or "instagram"
          timestamp = post.date_utc.strftime("%Y%m%d")
          ext = ".mp4" if is_video else ".jpg"
          filename = sanitize_filename(f"{owner}_{shortcode}_{timestamp}{ext}")

          status_placeholder.info(f"⬇️ Fetching Instagram {'video' if is_video else 'image'}: {filename}...")

          response = requests.get(target_url, stream=True, timeout=45)
          response.raise_for_status()

          file_data = BytesIO(response.content) # Read into memory
          mime_type = "video/mp4" if is_video else "image/jpeg"
          logging.info(f"Instagram media fetched. Type: {'Video' if is_video else 'Image'}. Filename: {filename}")

          display_download_button(file_data.getvalue(), filename, mime_type, status_placeholder)
          return True

     except instaloader.exceptions.PrivateProfileNotFollowedException:
          st.error("❌ Failed: Profile is private or requires login.")
          status_placeholder.empty()
          return False
     except instaloader.exceptions.LoginRequiredException:
          st.error("❌ Failed: Login required to access this content.")
          status_placeholder.empty()
          return False
     except instaloader.exceptions.NotFoundException:
          st.error("❌ Failed: Instagram post not found (404).")
          status_placeholder.empty()
          return False
     except instaloader.exceptions.ConnectionException as e:
         logging.error(f"Instaloader Connection Error for {link}: {e}", exc_info=True)
         st.error(f"❌ Connection Error with Instagram: {e}")
         status_placeholder.empty()
         return False
     except requests.exceptions.RequestException as e:
         logging.error(f"Network Error downloading Instagram media from {target_url}: {e}", exc_info=True)
         st.error(f"❌ Network Error downloading the media file: {e}")
         status_placeholder.empty()
         return False
     except Exception as e:
         logging.error(f"General Error during Instagram download for {link}: {e}", exc_info=True)
         st.error(f"❌ An unexpected error occurred with Instagram: {str(e)}")
         status_placeholder.empty()
         return False

# --- yt-dlp Functions ---

def get_video_info_ydl(link):
    """Gets video info using yt-dlp WITHOUT downloading."""
    logging.info(f"Fetching info for: {link}")
    # Define cookie file path (relative to script)
    # IMPORTANT: Ensure cookies.txt is in the same directory or adjust path
    cookie_file_path = 'cookies.txt'
    ydl_opts = {
        'quiet': True, 'noplaylist': True, 'format': 'bv*+ba/b',
        'getfilename': True, 'skip_download': True,
        # --- ADD COOKIE FILE FOR INFO CHECK ---
        'cookiefile': cookie_file_path if os.path.exists(cookie_file_path) else None,
        # ------------------------------------
    }
    if not ydl_opts['cookiefile']:
         logging.warning("cookies.txt not found for get_video_info_ydl. Authentication may fail.")

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(link, download=False)
            file_size = info_dict.get('filesize_approx') or info_dict.get('filesize')
            if not file_size and info_dict.get('requested_formats'):
                 file_size = sum(fmt.get('filesize', 0) or fmt.get('filesize_approx', 0) for fmt in info_dict['requested_formats'] if fmt)
            elif not file_size and info_dict.get('format_id'):
                 file_size = info_dict.get('filesize')

            title = info_dict.get('title', 'download')
            filename = info_dict.get('_filename') or f"{sanitize_filename(title)}.{info_dict.get('ext', 'mp4')}"
            filename = sanitize_filename(os.path.basename(filename))

            logging.info(f"Info fetched: Title='{title}', Size={file_size}, Filename='{filename}'")
            return file_size, filename
    except yt_dlp.utils.DownloadError as e:
         logging.error(f"yt-dlp Info Error for {link}: {e}")
         error_map = {'Unsupported URL': "Unsupported URL", 'HTTP Error 403': "Access Denied (403)", 'Login required': "Login Required"}
         for key, msg in error_map.items():
              if key in str(e): return None, msg
         return None, f"yt-dlp Error"
    except Exception as e:
        logging.error(f"General Info Error for {link}: {e}", exc_info=True)
        return None, "Error fetching info"


def download_with_ydl(link, filename_hint, status_placeholder):
    """Downloads using yt-dlp to a temporary file and returns bytes and final filename."""
    logging.info(f"Starting yt-dlp download for: {link}")
    status_placeholder.info("⚙️ Initializing yt-dlp...")

    # Define the progress hook function
    def _progress_hook(d):
        if d['status'] == 'downloading':
            percent_str = d.get('_percent_str', '...?%').strip()
            percent_val = percent_str.replace('%', '').strip()
            if '?' in percent_val: percent_val = '...'
            status_placeholder.info(f"⏳ Preparing Download: {percent_val}%")
        elif d['status'] == 'finished':
            status_placeholder.info("✅ Download complete, processing file...")
        elif d['status'] == 'error':
             status_placeholder.error("❌ Error during download process.")

    with tempfile.TemporaryDirectory() as tmp_dir:
        base_name = sanitize_filename(os.path.splitext(filename_hint)[0])
        outtmpl = os.path.join(tmp_dir, f"{base_name}.%(ext)s")

        # Define cookie file path (relative to script)
        # IMPORTANT: Ensure cookies.txt is in the same directory or adjust path
        cookie_file_path = 'cookies.txt'

        ydl_opts = {
            'format': 'bv*+ba/b',
            'merge_output_format': 'mp4',
            'outtmpl': outtmpl,
            'quiet': True,
            'verbose': False,
            'noprogress': True,
            'noplaylist': True,
            # --- ADD COOKIE FILE PATH HERE ---
            # Use cookies only if the file exists
            'cookiefile': cookie_file_path if os.path.exists(cookie_file_path) else None,
            # ---------------------------------
            'progress_hooks': [_progress_hook],
            'postprocessor_hooks': [lambda d: status_placeholder.info(f"⚙️ Merging formats...") if d['status'] == 'started' and d['postprocessor'] == 'Merger' else None],
        }

        # Log a warning if cookies are expected but not found
        if not ydl_opts['cookiefile']:
             logging.warning("cookies.txt not found. Downloads requiring authentication will likely fail.")
             # You might want to inform the user in the UI as well if needed:
             # status_placeholder.warning("Cookie file not found. Authentication may fail.")

        downloaded_file_path = None
        final_filename = filename_hint

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                status_placeholder.info(f"⬇️ Starting download: {filename_hint}...")
                ydl.download([link])

                files_in_tmp = os.listdir(tmp_dir)
                if not files_in_tmp:
                    logging.error("yt-dlp download finished, but no file found.")
                    return None, "Download failed (no file generated)."

                downloaded_file_path = os.path.join(tmp_dir, files_in_tmp[0])
                final_filename = files_in_tmp[0]
                logging.info(f"File downloaded to: {downloaded_file_path}")

                status_placeholder.info(f"💾 Reading file: {final_filename}...")
                # WARNING: Memory limit issue here
                with open(downloaded_file_path, "rb") as f:
                    file_data = f.read()
                logging.info(f"Read {len(file_data)} bytes.")

                status_placeholder.empty() # Clear status before returning
                return file_data, final_filename

        except yt_dlp.utils.DownloadError as e:
            error_str = str(e)
            logging.error(f"yt-dlp DownloadError for {link}: {error_str}", exc_info=True)
            if 'HTTP Error 403' in error_str:
                 error_message = (
                    "Error: Access Denied (HTTP 403 Forbidden).\n"
                    "This often means the platform blocked the request. Possible reasons:\n"
                    "- Video requires login (age/privacy restricted).\n"
                    "- High traffic from server / Rate limiting.\n"
                    "- Platform changes blocking yt-dlp (ensure it's up-to-date via requirements.txt).\n"
                    "- Regional blocks."
                 )
                 # Add note if cookies were used but failed
                 if ydl_opts.get('cookiefile'):
                      error_message += "\n- Authentication via cookies failed or was insufficient."
                 return None, error_message
            elif 'Unsupported URL' in error_str: return None, f"Error: Unsupported URL for yt-dlp."
            # Check specifically for authentication required errors
            elif 'confirm your age' in error_str.lower() or 'login required' in error_str.lower() or 'video is private' in error_str.lower():
                 if ydl_opts.get('cookiefile'):
                      return None, "Error: Login/Age check failed even with cookies. Cookies might be expired or invalid."
                 else:
                      return None, "Error: This content requires login/age verification (Cookies needed)."
            else: return None, f"yt-dlp Download Error: {error_str[:150]}..."
        except Exception as e:
            logging.error(f"Unexpected Error during yt-dlp download for {link}: {e}", exc_info=True)
            return None, f"An unexpected error occurred: {str(e)}"
        finally:
             logging.info(f"Temporary directory {tmp_dir} will be cleaned up.")

# --- Other Downloaders (TikTok, Drive, Generic - unchanged logic) ---
# ... (Keep the functions get_drive_download_link, download_tiktok, download_generic exactly as they were in the previous version) ...
def get_drive_download_link(link):
    """Attempts to create a direct download link for Google Drive."""
    try:
        match = re.search(r'/d/([^/]+)', link)
        if not match: return None
        file_id = match.group(1)
        download_url = f"https://drive.google.com/uc?export=download&id={file_id}&confirm=t"
        return download_url
    except Exception as e:
        logging.error(f"Failed to parse Google Drive link {link}: {e}")
        return None

def download_tiktok(link, status_placeholder):
    """Downloads TikTok using an external API."""
    api_url = f"https://www.tikwm.com/api/?url={link}"
    logging.info(f"Attempting TikTok download via API: {api_url}")
    status_placeholder.info("🎶 Contacting TikTok download service (tikwm.com)...")
    try:
        response = requests.get(api_url, timeout=15)
        response.raise_for_status()
        data = response.json()

        if data.get("code") == 0 and data.get("data") and data['data'].get("play"):
            video_url = data["data"]["play"]
            title = data["data"].get("title", "tiktok_video")
            author = data["data"].get("author", {}).get("unique_id", "user")
            file_name = sanitize_filename(f"{author}_{title}.mp4")

            status_placeholder.info(f"⬇️ Fetching TikTok video: {file_name}...")
            video_response = requests.get(video_url, stream=True, timeout=30)
            video_response.raise_for_status()

            file_data = BytesIO(video_response.content) # Read into memory
            logging.info(f"TikTok video fetched: {file_name}")
            display_download_button(file_data.getvalue(), file_name, "video/mp4", status_placeholder)
            return True
        else:
            error_msg = data.get("msg", "Unknown API error")
            logging.error(f"TikTok API Error for {link}: {error_msg}")
            st.error(f"❌ TikTok download failed (API: tikwm.com): {error_msg}")
            status_placeholder.empty()
            return False
    except requests.exceptions.RequestException as e:
        logging.error(f"Network Error during TikTok download for {link}: {e}", exc_info=True)
        st.error(f"❌ Network Error connecting to TikTok service: {e}")
        status_placeholder.empty()
        return False
    except json.JSONDecodeError as e:
        logging.error(f"JSON Decode Error during TikTok download for {link}: {e}", exc_info=True)
        st.error("❌ Error reading response from TikTok service.")
        status_placeholder.empty()
        return False
    except Exception as e:
        logging.error(f"General Error during TikTok download for {link}: {e}", exc_info=True)
        st.error(f"❌ An unexpected error occurred with TikTok: {str(e)}")
        status_placeholder.empty()
        return False

def download_generic(link, status_placeholder, source_response=None):
    """Attempts a generic download using requests. Can reuse a response."""
    logging.info(f"Attempting generic download for: {link}")
    status_placeholder.info("🌐 Attempting direct file download...")
    try:
        if source_response:
             response = source_response
             response.raise_for_status()
        else:
             response = requests.get(link, stream=True, timeout=15, allow_redirects=True)
             response.raise_for_status()

        file_name = "downloaded_file"
        content_disposition = response.headers.get('content-disposition')
        if content_disposition:
             fn_match = re.search(r'filename\*?=(?:UTF-8\'\')?([^;]+)', content_disposition, flags=re.IGNORECASE)
             if fn_match:
                  potential_name = unquote(fn_match.group(1).strip().strip('"'))
                  if '.' in potential_name and not potential_name.endswith('.'):
                       file_name = sanitize_filename(potential_name)
        if file_name == "downloaded_file":
            parsed_url = urlparse(link)
            path_part = parsed_url.path.strip('/')
            if path_part and '.' in os.path.basename(path_part):
                file_name = sanitize_filename(unquote(os.path.basename(path_part))) or file_name

        content_type = response.headers.get('content-type', 'application/octet-stream').split(';')[0]

        status_placeholder.info(f"⬇️ Downloading '{file_name}'...")
        file_data = BytesIO(response.content) # Read into memory
        logging.info(f"Generic download fetched: {file_name}")
        display_download_button(file_data.getvalue(), file_name, content_type, status_placeholder)
        return True
    except requests.exceptions.RequestException as e:
        logging.error(f"Network Error during generic download for {link}: {e}", exc_info=True)
        st.error(f"❌ Failed to retrieve file: Network Error ({e})")
        status_placeholder.empty()
        return False
    except Exception as e:
        logging.error(f"General Error during generic download for {link}: {e}", exc_info=True)
        st.error(f"❌ An unexpected error occurred during generic download: {str(e)}")
        status_placeholder.empty()
        return False

# --- Main Download Logic (Router - unchanged) ---

def route_download(link, status_placeholder):
    """Determines the download method based on the link."""
    if not link or not link.strip().startswith(('http://', 'https://')):
         st.error("❌ Invalid URL. Please enter a valid link starting with http:// or https://")
         status_placeholder.empty()
         return

    parsed_url = urlparse(link)
    domain = parsed_url.netloc.lower()

    # --- Routing Logic ---
    if "drive.google.com" in domain:
        status_placeholder.info("🚗 Handling Google Drive link...")
        download_url = get_drive_download_link(link)
        if not download_url:
            st.error("❌ Could not parse Google Drive link format.")
            status_placeholder.empty()
            return
        try:
             response = requests.get(download_url, stream=True, timeout=20)
             response.raise_for_status()
             if 'text/html' in response.headers.get('Content-Type', '').lower():
                  st.error("❌ Google Drive link requires confirmation/login or isn't shared correctly.")
                  status_placeholder.empty()
                  return
             status_placeholder.info("Google Drive link seems direct...")
             download_generic(download_url, status_placeholder, source_response=response)
        except requests.exceptions.RequestException as e:
             st.error(f"❌ Failed to retrieve from Google Drive: Network Error ({e})")
             status_placeholder.empty()
        except Exception as e:
             st.error(f"❌ An unexpected error occurred with Google Drive: {str(e)}")
             status_placeholder.empty()

    elif "instagram.com" in domain:
        download_instagram(link, status_placeholder)

    elif "tiktok.com" in domain:
        download_tiktok(link, status_placeholder)

    else:
        # Check if likely yt-dlp target (keep list as is)
        ydl_domains = [
            '.youtube.com', 'youtu.be', 'facebook.com', 'fb.watch', 'twitter.com',
            'vimeo.com', 'dailymotion.com', 'soundcloud.com', 'twitch.tv', 'bandcamp.com',
            'bilibili.com',
        ]
        is_ydl_target = any(domain.endswith(d) for d in ydl_domains) or domain.startswith('youtube.') or domain.startswith('youtube.com') or domain.startswith('youtu.be')

        if is_ydl_target:
            status_placeholder.info("🔎 Analyzing link with yt-dlp...")
            file_size, filename_or_error = get_video_info_ydl(link) # Uses cookies if available

            if filename_or_error is None or filename_or_error in ["Unsupported URL", "Access Denied (403)", "Login Required", "yt-dlp Error", "Error fetching info"]:
                 error_msg = filename_or_error or "Unknown analysis error"
                 st.error(f"❌ Analysis failed: {error_msg}")
                 status_placeholder.empty()
                 return

            size_info = f"~{round(file_size / (1024 * 1024), 2)} MB" if file_size else "Unknown Size"
            status_placeholder.info(f"ℹ️ Media detected: '{os.path.splitext(filename_or_error)[0]}', Size: **{size_info}**")
            # Download with yt-dlp (uses cookies if available)
            file_data, message = download_with_ydl(link, filename_or_error, status_placeholder)

            if file_data:
                 mime_type = "application/octet-stream"
                 if '.' in message: ext = message.split('.')[-1].lower()
                 else: ext = ''
                 if ext == 'mp4': mime_type = 'video/mp4'
                 elif ext == 'mp3': mime_type = 'audio/mpeg'
                 elif ext == 'webm': mime_type = 'video/webm'
                 elif ext == 'mkv': mime_type = 'video/x-matroska'
                 elif ext == 'jpg' or ext == 'jpeg': mime_type = 'image/jpeg'
                 elif ext == 'png': mime_type = 'image/png'
                 elif ext == 'webp': mime_type = 'image/webp'
                 display_download_button(file_data, message, mime_type, status_placeholder)
            else:
                 st.error(f"❌ Download Failed: {message}")
                 status_placeholder.empty()

        else:
             # Generic Fallback
             status_placeholder.warning("Domain not specifically handled, attempting generic download...")
             download_generic(link, status_placeholder)

# --- Streamlit UI (unchanged) ---
def main():
    st.set_page_config(page_title="Universal Media Downloader", page_icon="🌐", layout="wide")
    st.title("🌐 Universal Media Downloader")

    col1, col2 = st.columns([3, 1])
    with col1:
        link = st.text_input("🔗 Enter Media Link (URL):", key="media_link_input", placeholder="https://...")
    with col2:
        st.write("") # Spacer
        st.write("") # Spacer
        download_button = st.button("⬇️ Get Media", key="download_button", use_container_width=True)

    status_placeholder = st.container() # Use a container to manage status updates

    if download_button:
        status_placeholder.empty() # Clear previous status/button
        msg_container = status_placeholder.container()

        if link and link.strip():
            with st.spinner("Processing link..."):
                 route_download(link.strip(), msg_container) # Pass container for messages
        else:
            msg_container.error("❌ Please provide a valid URL.")

    # Expander (keep updated info)
    with st.expander("📌 Supported Sites & Info", expanded=False):
        st.markdown("""
            * **Attempts to Support:** YouTube, Facebook, Twitter, Instagram (Public Posts/Reels), TikTok*, Google Drive*, Vimeo, Dailymotion, Soundcloud, Twitch Clips/VODs, Bandcamp, Bilibili, and many other sites via `yt-dlp`. (Cookie support added for authenticated downloads where needed).
            * **Generic Downloader:** Tries direct downloads for other file URLs.
            * **Features:** Shows estimated file size when available. Downloads directly to your browser.
            * **Important Notes:**
                * `*`TikTok (uses external API) & Google Drive (direct links) support can be unreliable.
                * **Login/Cookies:** This version attempts to use a `cookies.txt` file if present. This primarily helps with age/privacy restricted content. **Using cookies is a security risk if not managed carefully.** Login required for Instagram profiles/stories etc. will still fail.
                * **Platform Blocking:** Sites like YouTube may still block downloads (e.g., 403 errors), even with cookies, due to IP limits etc.
                * **Large Files:** Downloads might fail on the server due to memory limits (~1GB).
                * **Cookie Expiration:** `cookies.txt` needs manual updates when cookies expire.
        """)
        st.caption("Powered by yt-dlp, Instaloader, requests, and Streamlit.")

if __name__ == "__main__":
    main()
