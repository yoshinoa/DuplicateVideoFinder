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


colorama.init()

class VideoDeduplicator:
    def __init__(self, folder, threshold=5.0, frame_skip=30, batch_mode=False, move_duplicates=None):
        self.folder = folder
        self.threshold = threshold
        self.frame_skip = frame_skip
        self.batch_mode = batch_mode
        self.move_duplicates = move_duplicates
        self.conn = self.get_db()
        self.videos = self.get_video_files(folder)
        self.fingerprints = {}
        
        
        if self.move_duplicates:
            os.makedirs(self.move_duplicates, exist_ok=True)
    
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

    def prompt_duplicate_action(self, file1, file2):
        """Prompt user for action when duplicate is found."""
        
        size1 = self.format_size(file1)
        size2 = self.format_size(file2)
        duration1 = self.format_duration(file1)
        duration2 = self.format_duration(file2)
        
        print(f"\n{Fore.YELLOW}🔍 Duplicate detected:{Style.RESET_ALL}")
        print(f"{Fore.CYAN}[1] {os.path.basename(file1)}{Style.RESET_ALL}")
        print(f"   📁 Path: {file1}")
        print(f"   📊 Size: {size1}")
        print(f"   ⏱️ Duration: {duration1}")
        print()
        print(f"{Fore.CYAN}[2] {os.path.basename(file2)}{Style.RESET_ALL}")
        print(f"   📁 Path: {file2}")
        print(f"   📊 Size: {size2}")
        print(f"   ⏱️ Duration: {duration2}")
        print()
        
        if self.batch_mode:
            choice = "1"  
            print(f"{Fore.GREEN}Batch mode: Automatically keeping file 1 and removing file 2{Style.RESET_ALL}")
        elif self.move_duplicates:
            choice = "4"  
            print(f"{Fore.GREEN}Moving duplicate to: {self.move_duplicates}{Style.RESET_ALL}")
        else:
            print(f"{Fore.CYAN}[1] Keep {os.path.basename(file1)} (delete the other){Style.RESET_ALL}")
            print(f"{Fore.CYAN}[2] Keep {os.path.basename(file2)} (delete the other){Style.RESET_ALL}")
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
                os.remove(file2)
                self.conn.execute("DELETE FROM videos WHERE path = ?", (file2,))
                self.conn.commit()
                print(f"{Fore.RED}❌ Deleted: {file2}{Style.RESET_ALL}")
            except Exception as e:
                print(f"{Fore.RED}Error deleting {file2}: {str(e)}{Style.RESET_ALL}")
        elif choice == "2":
            try:
                os.remove(file1)
                self.conn.execute("DELETE FROM videos WHERE path = ?", (file1,))
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
                self.conn.execute("UPDATE videos SET path = ? WHERE path = ?", (dest, file2))
                self.conn.commit()
                print(f"{Fore.GREEN}📦 Moved to: {dest}{Style.RESET_ALL}")
            except Exception as e:
                print(f"{Fore.RED}Error moving {file2}: {str(e)}{Style.RESET_ALL}")
        elif choice == "q":
            print(f"{Fore.YELLOW}Exiting program...{Style.RESET_ALL}")
            exit(0)

    def compute_video_fingerprint(self, frames):
        """Compute perceptual hash for each frame."""
        if not frames:
            return []
        return [imagehash.phash(frame) for frame in frames]

    def compare_fingerprints(self, hash_list1, hash_list2):
        """Compare two lists of image hashes."""
        if not hash_list1 or not hash_list2:
            return float('inf')  
            
        min_len = min(len(hash_list1), len(hash_list2))
        if min_len == 0:
            return float('inf')
            
        distances = [hash_list1[i] - hash_list2[i] for i in range(min_len)]
        return np.mean(distances)

    def is_duplicate(self, hash1, hash2):
        """Check if two hash lists represent duplicate videos."""
        distance = self.compare_fingerprints(hash1, hash2)
        return distance < self.threshold, distance

    def get_video_files(self, folder, extensions=(".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".m4v")):
        """Get all video files in the specified folder."""
        video_files = []
        print(f"{Fore.BLUE}Scanning for videos in: {folder}{Style.RESET_ALL}")
        
        for root, _, files in os.walk(folder):
            for file in files:
                if file.lower().endswith(extensions):
                    video_files.append(os.path.join(root, file))
        
        return video_files

    def get_db(self):
        """Initialize database connection."""
        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "video_hashes.db")
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT UNIQUE,
                sha256 TEXT,
                frame_hashes TEXT,
                processed_date TEXT
            )
        """)
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

    def get_or_compute_fingerprint(self, path):
        """Get fingerprint from database or compute it."""
        try:
            
            if not os.path.exists(path):
                print(f"{Fore.RED}File not found: {path}{Style.RESET_ALL}")
                return []
                
            
            sha = self.compute_sha256(path)
            if not sha:
                return []
                
            
            cur = self.conn.cursor()
            cur.execute("SELECT frame_hashes FROM videos WHERE sha256 = ?", (sha,))
            row = cur.fetchone()

            if row:
                try:
                    hash_list = json.loads(row[0])
                    return [imagehash.ImageHash(np.array(h)) for h in hash_list]
                except:
                    
                    pass

            
            frames = self.extract_keyframes(path)
            hashes = self.compute_video_fingerprint(frames)
            
            
            processed_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if hashes:
                try:
                    cur.execute(
                        "INSERT OR REPLACE INTO videos (path, sha256, frame_hashes, processed_date) VALUES (?, ?, ?, ?)",
                        (path, sha, json.dumps([h.hash.tolist() for h in hashes]), processed_date)
                    )
                    self.conn.commit()
                except Exception as e:
                    print(f"{Fore.RED}Database error for {path}: {str(e)}{Style.RESET_ALL}")
            
            return hashes
        except Exception as e:
            print(f"{Fore.RED}Error processing {path}: {str(e)}{Style.RESET_ALL}")
            return []

    def process_videos(self):
        """Process all videos and find duplicates."""
        if not self.videos:
            print(f"{Fore.YELLOW}No videos found in {self.folder}{Style.RESET_ALL}")
            return
            
        print(f"{Fore.GREEN}Found {len(self.videos)} videos. Processing...{Style.RESET_ALL}")
        
        
        for path in tqdm.tqdm(self.videos, desc="Analyzing videos", unit="video"):
            self.fingerprints[path] = self.get_or_compute_fingerprint(path)

        print(f"\n{Fore.GREEN}Checking for duplicates...{Style.RESET_ALL}")
        checked = set()
        found_duplicates = False
        
        
        combinations = list(itertools.combinations(self.videos, 2))
        for v1, v2 in tqdm.tqdm(combinations, desc="Comparing videos", unit="pair"):
            if not os.path.exists(v1) or not os.path.exists(v2):
                continue
                
            pair_key = tuple(sorted((v1, v2)))
            if pair_key in checked:
                continue
                
            checked.add(pair_key)
            
            
            if not self.fingerprints[v1] or not self.fingerprints[v2]:
                continue
                
            is_dup, dist = self.is_duplicate(self.fingerprints[v1], self.fingerprints[v2])
            
            if is_dup:
                found_duplicates = True
                self.prompt_duplicate_action(v1, v2)
        
        if not found_duplicates:
            print(f"{Fore.GREEN}✅ No duplicates found!{Style.RESET_ALL}")
        
        
        print(f"\n{Fore.BLUE}📊 Summary:{Style.RESET_ALL}")
        print(f"• Videos processed: {len(self.videos)}")
        print(f"• Pairs compared: {len(checked)}")

def main():
    parser = argparse.ArgumentParser(
        description="Video Duplicate Finder - Find and manage duplicate videos easily",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("folder", type=str, help="Path to the folder containing videos")
    parser.add_argument("--threshold", type=float, default=5.0, 
                        help="Similarity threshold (lower value = more strict matching)")
    parser.add_argument("--skip", type=int, default=30, 
                        help="Number of frames to skip between keyframes")
    parser.add_argument("--batch", action="store_true", 
                        help="Batch mode: automatically keep first file in each duplicate pair")
    parser.add_argument("--move", type=str, 
                        help="Move duplicates to specified folder instead of deleting")

    args = parser.parse_args()
    
    
    print(f"\n{Fore.BLUE}{'=' * 60}{Style.RESET_ALL}")
    print(f"{Fore.BLUE}🎬 Video Duplicate Finder{Style.RESET_ALL}")
    print(f"{Fore.BLUE}{'=' * 60}{Style.RESET_ALL}")
    
    
    deduplicator = VideoDeduplicator(
        args.folder, 
        threshold=args.threshold,
        frame_skip=args.skip,
        batch_mode=args.batch,
        move_duplicates=args.move
    )
    deduplicator.process_videos()
    
    print(f"\n{Fore.GREEN}Done!{Style.RESET_ALL}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}Program interrupted by user. Exiting...{Style.RESET_ALL}")
    except Exception as e:
        print(f"\n{Fore.RED}An unexpected error occurred: {str(e)}{Style.RESET_ALL}")
