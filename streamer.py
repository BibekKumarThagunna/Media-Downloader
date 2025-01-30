import streamlit as st
import requests
import yt_dlp
import os
from urllib.parse import urlparse
from io import BytesIO
import instaloader
from urllib.parse import urlencode

# Function to get video details before downloading
def get_video_info(link):
    ydl_opts = {
        'quiet': True,
        'noplaylist': True,
        'format': 'bestvideo+bestaudio/best'
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info_dict = ydl.extract_info(link, download=False)
        file_size = info_dict.get('filesize_approx', None)
        title = info_dict.get('title', 'video')
        return file_size, title

# Function to handle Google Drive direct download link
def get_drive_download_link(link):
    file_id = link.split('/d/')[1].split('/')[0]
    download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
    return download_url

# Function to download Instagram post or reel (image/video)
def download_instagram_content(link):
    loader = instaloader.Instaloader()
    try:
        post = loader.get_post(link)
        file_name = post.shortcode + '.' + post.url.split('.')[-1]
        st.write(f"📦 File Size: **{post.video_height * post.video_width / 1048576:.2f} MB**")

        response = requests.get(post.url, stream=True)
        file_data = BytesIO(response.content)

        st.download_button(
            label="📥 Download Instagram Content",
            data=file_data,
            file_name=file_name,
            mime="application/octet-stream"
        )

    except Exception as e:
        st.error(f"❌ Error: {str(e)}")

# Function to handle download from different websites
def stream_download(link):
    try:
        # Handle Google Drive link
        if "drive.google.com" in link:
            download_url = get_drive_download_link(link)
            response = requests.get(download_url, stream=True)

            if response.status_code == 200:
                file_name = link.split("/")[-2] + '.file'
                st.write(f"📦 File Size: **{len(response.content) / (1024 * 1024):.2f} MB**")
                file_data = BytesIO(response.content)
                st.download_button(
                    label="📥 Download Now",
                    data=file_data,
                    file_name=file_name,
                    mime="application/octet-stream"
                )
            else:
                st.error("❌ Failed to retrieve the file from Google Drive.")
            return

        # Handle YouTube, YouTube Shorts, Twitter, Facebook, Instagram links
        if any(domain in link for domain in ['youtube.com', 'youtu.be', 'twitter.com', 'facebook.com', 'instagram.com']):
            file_size, title = get_video_info(link)

            if file_size:
                file_size_mb = round(file_size / (1024 * 1024), 2)
                st.write(f"📦 Estimated File Size: **{file_size_mb} MB**")

            ydl_opts = {
                'format': 'bestvideo+bestaudio/best',
                'merge_output_format': 'mp4',
                'quiet': True,
                'noplaylist': True,
                'outtmpl': f"{title}.mp4",
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                st.write("🔄 Extracting download link...")
                info_dict = ydl.extract_info(link, download=True)
                output_file = f"{title}.mp4"

            st.success("✅ Download is ready!")

            with open(output_file, "rb") as file:
                st.download_button(
                    label="📥 Download Video",
                    data=file,
                    file_name=output_file,
                    mime="video/mp4"
                )

            os.remove(output_file)
        else:
            # Generic download for any file
            st.write("🌐 Downloading file...")

            response = requests.get(link, stream=True)
            if response.status_code == 200:
                file_name = link.split("/")[-1]
                file_size = len(response.content) / (1024 * 1024)  # Convert to MB
                st.write(f"📦 File Size: **{file_size:.2f} MB**")
                file_data = BytesIO(response.content)

                st.download_button(
                    label="📥 Download Now",
                    data=file_data,
                    file_name=file_name,
                    mime="application/octet-stream"
                )
            else:
                st.error("❌ Failed to retrieve the file.")
    
    except Exception as e:
        st.error(f"❌ Error: {str(e)}")

# Streamlit UI
def main():
    st.title("🌐 Universal Media Downloader")

    with st.expander("📌 Features"):
        st.write("""
            - ✅ **Download media from YouTube, Instagram, Facebook, Google Drive, Twitter, and many other websites**.
            - ✅ Supports **video, image, and other types of files**.
            - ✅ Provides **file size and download progress** before downloading.
        """)

    link = st.text_input("🔗 Enter the media link:")

    if st.button("📥 Download Now"):
        if link:
            stream_download(link)
        else:
            st.error("❌ Please provide a valid URL.")

if __name__ == "__main__":
    main()
