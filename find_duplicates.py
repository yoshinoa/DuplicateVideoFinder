import cv2
import imagehash
from PIL import Image
import numpy as np
import os
import argparse
import itertools
import hashlib
import sqlite3
import json
import tqdm
import colorama
from colorama import Fore, Style
import shutil
from datetime import datetime
import sys
import subprocess

current_dir = os.getcwd()
if len(sys.argv) > 1 and not os.path.isabs(sys.argv[1]):
    sys.argv[1] = os.path.join(current_dir, sys.argv[1])
colorama.init()

class MediaDeduplicator:
    def __init__(self, folder, threshold=5.0, frame_skip=30, batch_mode=False, move_duplicates=None):
        self.folder = folder
        self.threshold = threshold
        self.frame_skip = frame_skip
        self.batch_mode = batch_mode
        self.move_duplicates = move_duplicates
        self.conn = self.get_db()
        self.video_extensions = (".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".m4v")
        self.photo_extensions = (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tiff", ".tif", ".webp", ".heic", ".raw")
        self.media_files = self.get_media_files(folder)
        self.fingerprints = {}
        
        if self.move_duplicates:
            os.makedirs(self.move_duplicates, exist_ok=True)
    
    def is_video(self, file_path):
        """Check if file is a video."""
        return file_path.lower().endswith(self.video_extensions)
    
    def is_photo(self, file_path):
        """Check if file is a photo."""
        return file_path.lower().endswith(self.photo_extensions)
    
    def delete_file(self, file_path):
        """Delete a file, using sudo if necessary for protected directories."""
        try:
            os.remove(file_path)
            self.conn.execute("DELETE FROM media WHERE path = ?", (file_path,))
            self.conn.commit()
            print(f"{Fore.RED}❌ Deleted: {file_path}{Style.RESET_ALL}")
            return True
        except Exception as e:
            print(f"{Fore.YELLOW}Regular deletion failed: {str(e)}")
            print(f"{Fore.YELLOW}Using sudo to delete file: {file_path}{Style.RESET_ALL}")
            try:
                result = subprocess.run(['sudo', 'rm', file_path], 
                                    capture_output=True, text=True, check=False)
                
                if result.returncode == 0:
                    self.conn.execute("DELETE FROM media WHERE path = ?", (file_path,))
                    self.conn.commit()
                    print(f"{Fore.RED}❌ Deleted with sudo: {file_path}{Style.RESET_ALL}")
                    return True
                else:
                    print(f"{Fore.RED}Error with sudo deletion: {result.stderr}{Style.RESET_ALL}")
                    return False
            except Exception as e:
                print(f"{Fore.RED}Error with sudo command: {str(e)}{Style.RESET_ALL}")
                return False
    
    def extract_keyframes(self, video_path):
        """Extract keyframes from video file."""
        try:
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                print(f"{Fore.RED}Error: Could not open video {video_path}{Style.RESET_ALL}")
                return []
                
            keyframes = []
            count = 0
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            
            if total_frames <= 0:
                total_frames = 1000  
                
            fps = cap.get(cv2.CAP_PROP_FPS)
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            
            while cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    break

                if count % self.frame_skip == 0:
                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    pil_img = Image.fromarray(rgb_frame)
                    keyframes.append(pil_img)

                count += 1

            cap.release()
            return keyframes
        except Exception as e:
            print(f"{Fore.RED}Error processing {video_path}: {str(e)}{Style.RESET_ALL}")
            return []

    def load_photo(self, photo_path):
        """Load and return a photo as PIL Image."""
        try:
            image = Image.open(photo_path)
            # Convert RGBA to RGB if needed
            if image.mode == 'RGBA':
                image = image.convert('RGB')
            return image
        except Exception as e:
            print(f"{Fore.RED}Error loading photo {photo_path}: {str(e)}{Style.RESET_ALL}")
            return None

    def format_size(self, path):
        """Format file size to human-readable format."""
        try:
            size = os.path.getsize(path)
            if size >= 1024 ** 3:
                return f"{size / (1024 ** 3):.2f} GB"
            elif size >= 1024 ** 2:
                return f"{size / (1024 ** 2):.2f} MB"
            elif size >= 1024:
                return f"{size / 1024:.2f} KB"
            else:
                return f"{size} B"
        except:
            return "Unknown size"

    def format_duration(self, path):
        """Extract and format video duration."""
        if self.is_photo(path):
            return "N/A (Photo)"
            
        try:
            cap = cv2.VideoCapture(path)
            if not cap.isOpened():
                return "Unknown"
                
            fps = cap.get(cv2.CAP_PROP_FPS)
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            cap.release()
            
            if fps <= 0 or frame_count <= 0:
                return "Unknown"
                
            duration_sec = frame_count / fps
            
            if duration_sec >= 3600:
                hours = int(duration_sec // 3600)
                minutes = int((duration_sec % 3600) // 60)
                seconds = int(duration_sec % 60)
                return f"{hours}h {minutes}m {seconds}s"
            elif duration_sec >= 60:
                minutes = int(duration_sec // 60)
                seconds = int(duration_sec % 60)
                return f"{minutes}m {seconds}s"
            else:
                return f"{int(duration_sec)}s"
        except:
            return "Unknown"

    def get_media_type(self, path):
        """Get human-readable media type."""
        if self.is_video(path):
            return "Video"
        elif self.is_photo(path):
            return "Photo"
        else:
            return "Unknown"

    def prompt_duplicate_action(self, file1, file2):
        """Prompt user for action when duplicate is found."""
        size1 = self.format_size(file1)
        size2 = self.format_size(file2)
        duration1 = self.format_duration(file1)
        duration2 = self.format_duration(file2)
        type1 = self.get_media_type(file1)
        type2 = self.get_media_type(file2)
        
        print(f"\n{Fore.YELLOW}🔍 Duplicate detected:{Style.RESET_ALL}")
        print(f"{Fore.CYAN}[1] {os.path.basename(file1)}{Style.RESET_ALL}")
        print(f"   📁 Path: {file1}")
        print(f"   📊 Size: {size1}")
        print(f"   📹 Type: {type1}")
        print(f"   ⏱️ Duration: {duration1}")
        print()
        print(f"{Fore.CYAN}[2] {os.path.basename(file2)}{Style.RESET_ALL}")
        print(f"   📁 Path: {file2}")
        print(f"   📊 Size: {size2}")
        print(f"   📹 Type: {type2}")
        print(f"   ⏱️ Duration: {duration2}")
        print()
        
        if self.batch_mode:
            choice = "1"  
            print(f"{Fore.GREEN}Batch mode: Automatically keeping file 1 and removing file 2{Style.RESET_ALL}")
        elif self.move_duplicates:
            choice = "4"  
            print(f"{Fore.GREEN}Moving duplicate to: {self.move_duplicates}{Style.RESET_ALL}")
        else:
            print(f"{Fore.CYAN}[1] Keep {os.path.basename(file1)}{Style.RESET_ALL}")
            print(f"{Fore.CYAN}[2] Keep {os.path.basename(file2)}{Style.RESET_ALL}")
            print(f"{Fore.CYAN}[3] Keep both files{Style.RESET_ALL}")
            print(f"{Fore.CYAN}[4] Move duplicate to separate folder{Style.RESET_ALL}")
            print(f"{Fore.CYAN}[q] Quit program{Style.RESET_ALL}")
            
            while True:
                choice = input(f"{Fore.GREEN}What would you like to do? (1/2/3/4/q): {Style.RESET_ALL}").strip().lower()
                if choice in ["1", "2", "3", "4", "q"]:
                    break
                print(f"{Fore.RED}Invalid choice. Please try again.{Style.RESET_ALL}")
        
        if choice == "1":
            try:
                self.delete_file(file2)
                self.conn.execute("DELETE FROM media WHERE path = ?", (file2,))
                self.conn.commit()
                print(f"{Fore.RED}❌ Deleted: {file2}{Style.RESET_ALL}")
            except Exception as e:
                print(f"{Fore.RED}Error deleting {file2}: {str(e)}{Style.RESET_ALL}")
        elif choice == "2":
            try:
                self.delete_file(file1)
                self.conn.execute("DELETE FROM media WHERE path = ?", (file1,))
                self.conn.commit()
                print(f"{Fore.RED}❌ Deleted: {file1}{Style.RESET_ALL}")
            except Exception as e:
                print(f"{Fore.RED}Error deleting {file1}: {str(e)}{Style.RESET_ALL}")
        elif choice == "3":
            print(f"{Fore.GREEN}✅ Keeping both files{Style.RESET_ALL}")
        elif choice == "4":
            try:
                dest = os.path.join(self.move_duplicates, os.path.basename(file2))
                if os.path.exists(dest):
                    base, ext = os.path.splitext(dest)
                    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                    dest = f"{base}_{timestamp}{ext}"
                    
                shutil.move(file2, dest)
                self.conn.execute("UPDATE media SET path = ? WHERE path = ?", (dest, file2))
                self.conn.commit()
                print(f"{Fore.GREEN}📦 Moved to: {dest}{Style.RESET_ALL}")
            except Exception as e:
                print(f"{Fore.RED}Error moving {file2}: {str(e)}{Style.RESET_ALL}")
        elif choice == "q":
            print(f"{Fore.YELLOW}Exiting program...{Style.RESET_ALL}")
            exit(0)

    def compute_fingerprint(self, file_path):
        """Compute perceptual hash for media file."""
        if self.is_video(file_path):
            frames = self.extract_keyframes(file_path)
            if not frames:
                return []
            return [imagehash.phash(frame) for frame in frames]
        elif self.is_photo(file_path):
            photo = self.load_photo(file_path)
            if photo is None:
                return []
            # Return a single hash as a list for consistency with video processing
            return [imagehash.phash(photo)]
        else:
            return []

    def compare_fingerprints(self, hash_list1, hash_list2):
        """Compare two lists of image hashes."""
        if not hash_list1 or not hash_list2:
            return float('inf')  
            
        # For photos, we have single hashes, so compare directly
        if len(hash_list1) == 1 and len(hash_list2) == 1:
            return hash_list1[0] - hash_list2[0]
            
        # For videos, or when comparing video with photo, compare multiple hashes
        min_len = min(len(hash_list1), len(hash_list2))
        if min_len == 0:
            return float('inf')
            
        distances = [hash_list1[i] - hash_list2[i] for i in range(min_len)]
        return np.mean(distances)

    def is_duplicate(self, hash1, hash2):
        """Check if two hash lists represent duplicate files."""
        distance = self.compare_fingerprints(hash1, hash2)
        return distance < self.threshold, distance

    def get_media_files(self, folder):
        """Get all media files (videos and photos) in the specified folder."""
        media_files = []
        print(f"{Fore.BLUE}Scanning for media files in: {folder}{Style.RESET_ALL}")
        
        for root, _, files in os.walk(folder):
            for file in files:
                if file.lower().endswith(self.video_extensions + self.photo_extensions):
                    media_files.append(os.path.join(root, file))
        
        return media_files

    def get_db(self):
        """Initialize database connection."""
        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "media_hashes.db")
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS media (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT UNIQUE,
                sha256 TEXT,
                partial_id TEXT,
                media_type TEXT,
                hashes TEXT,
                processed_date TEXT
            )
        """)
        c.execute("PRAGMA table_info(media)")
        columns = [info[1] for info in c.fetchall()]
        if 'partial_id' not in columns:
            c.execute("ALTER TABLE media ADD COLUMN partial_id TEXT")
        
        conn.commit()
        return conn

    def compute_sha256(self, path):
        """Compute SHA256 hash of a file."""
        try:
            hasher = hashlib.sha256()
            with open(path, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except Exception as e:
            print(f"{Fore.RED}Error computing hash for {path}: {str(e)}{Style.RESET_ALL}")
            return None

    def compute_partial_hash(self, path, chunk_size=64*1024):
        """Compute hash of just the first chunk of a file."""
        try:
            file_size = os.path.getsize(path)
            hasher = hashlib.md5()
            with open(path, 'rb') as f:
                chunk = f.read(chunk_size)
                hasher.update(chunk)
            return f"{file_size}_{hasher.hexdigest()}"
        except Exception as e:
            print(f"{Fore.RED}Error computing partial hash for {path}: {str(e)}{Style.RESET_ALL}")
            return None

    def get_or_compute_fingerprint(self, path):
        """Get fingerprint from database or compute it using a faster check first."""
        try:
            if not os.path.exists(path):
                print(f"{Fore.RED}File not found: {path}{Style.RESET_ALL}")
                return []
            
            partial_id = self.compute_partial_hash(path)
            cur = self.conn.cursor()
            cur.execute("SELECT partial_id from media;")
            rows = cur.fetchall()
            if partial_id:
                cur = self.conn.cursor()
                cur.execute("SELECT hashes FROM media WHERE partial_id = ?", (partial_id,))
                row = cur.fetchone()
                
                if row:
                    try:
                        hash_list = json.loads(row[0])
                        return [imagehash.ImageHash(np.array(h)) for h in hash_list]
                    except:
                        pass
            
            sha = self.compute_sha256(path)
            print(sha)
            if not sha:
                return []
            
            media_type = "video" if self.is_video(path) else "photo"
            cur = self.conn.cursor()
            cur.execute("SELECT id, hashes, partial_id FROM media WHERE sha256 = ?", (sha,))
            row = cur.fetchone()

            if row:
                record_id, hashes_json, existing_partial_id = row
                
                if not existing_partial_id:
                    print(f"{Fore.GREEN}Updating existing record with partial_id: {partial_id}{Style.RESET_ALL}")
                    cur.execute(
                        "UPDATE media SET partial_id = ? WHERE id = ?",
                        (partial_id, record_id)
                    )
                    self.conn.commit()
                
                # Return the hashes
                try:
                    hash_list = json.loads(hashes_json)
                    return [imagehash.ImageHash(np.array(h)) for h in hash_list]
                except Exception as e:
                    print(f"{Fore.YELLOW}Error parsing hash from database: {str(e)}{Style.RESET_ALL}")

            hashes = self.compute_fingerprint(path)
            
            processed_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(hashes)
            if hashes:
                try:
                    cur.execute(
                        "INSERT OR REPLACE INTO media (path, sha256, partial_id, media_type, hashes, processed_date) VALUES (?, ?, ?, ?, ?, ?)",
                        (path, sha, partial_id, media_type, json.dumps([h.hash.tolist() for h in hashes]), processed_date)
                    )
                    self.conn.commit()
                except Exception as e:
                    print(f"{Fore.RED}Database error for {path}: {str(e)}{Style.RESET_ALL}")
            
            return hashes
        except Exception as e:
            print(f"{Fore.RED}Error processing {path}: {str(e)}{Style.RESET_ALL}")
            return []

    def process_media(self):
        """Process all media files and find duplicates."""
        if not self.media_files:
            print(f"{Fore.YELLOW}No media files found in {self.folder}{Style.RESET_ALL}")
            return
            
        # Count videos and photos
        video_count = sum(1 for f in self.media_files if self.is_video(f))
        photo_count = sum(1 for f in self.media_files if self.is_photo(f))
        
        print(f"{Fore.GREEN}Found {len(self.media_files)} media files ({video_count} videos, {photo_count} photos). Processing...{Style.RESET_ALL}")
        
        # Compute fingerprints
        for path in tqdm.tqdm(self.media_files, desc="Analyzing media", unit="file"):
            self.fingerprints[path] = self.get_or_compute_fingerprint(path)

        print(f"\n{Fore.GREEN}Checking for duplicates...{Style.RESET_ALL}")
        checked = set()
        found_duplicates = False
        
        # Compare all pairs
        combinations = list(itertools.combinations(self.media_files, 2))
        for v1, v2 in tqdm.tqdm(combinations, desc="Comparing files", unit="pair"):
            if not os.path.exists(v1) or not os.path.exists(v2):
                continue
                
            pair_key = tuple(sorted((v1, v2)))
            if pair_key in checked:
                continue
                
            checked.add(pair_key)
            
            # Skip if we don't have fingerprints for both files
            if not self.fingerprints[v1] or not self.fingerprints[v2]:
                continue
                
            is_dup, dist = self.is_duplicate(self.fingerprints[v1], self.fingerprints[v2])
            
            if is_dup:
                found_duplicates = True
                self.prompt_duplicate_action(v1, v2)
        
        if not found_duplicates:
            print(f"{Fore.GREEN}✅ No duplicates found!{Style.RESET_ALL}")
        
        print(f"\n{Fore.BLUE}📊 Summary:{Style.RESET_ALL}")
        print(f"• Media files processed: {len(self.media_files)}")
        print(f"  - Videos: {video_count}")
        print(f"  - Photos: {photo_count}")
        print(f"• Pairs compared: {len(checked)}")

def main():
    parser = argparse.ArgumentParser(
        description="Media Duplicate Finder - Find and manage duplicate videos and photos easily",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("folder", type=str, help="Path to the folder containing media files")
    parser.add_argument("--threshold", type=float, default=5.0, 
                        help="Similarity threshold (lower value = more strict matching)")
    parser.add_argument("--skip", type=int, default=30, 
                        help="Number of frames to skip between keyframes for videos")
    parser.add_argument("--batch", action="store_true", 
                        help="Batch mode: automatically keep first file in each duplicate pair")
    parser.add_argument("--move", type=str, 
                        help="Move duplicates to specified folder instead of deleting")

    args = parser.parse_args()
    
    print(f"\n{Fore.BLUE}{'=' * 60}{Style.RESET_ALL}")
    print(f"{Fore.BLUE}🎬📷 Media Duplicate Finder{Style.RESET_ALL}")
    print(f"{Fore.BLUE}{'=' * 60}{Style.RESET_ALL}")
    
    deduplicator = MediaDeduplicator(
        args.folder, 
        threshold=args.threshold,
        frame_skip=args.skip,
        batch_mode=args.batch,
        move_duplicates=args.move
    )
    deduplicator.process_media()
    
    print(f"\n{Fore.GREEN}Done!{Style.RESET_ALL}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}Program interrupted by user. Exiting...{Style.RESET_ALL}")
    except Exception as e:
        print(f"\n{Fore.RED}An unexpected error occurred: {str(e)}{Style.RESET_ALL}")