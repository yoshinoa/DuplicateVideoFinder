# Duplicate Video Finder

A tool to detect and manage duplicate videos based on visual similarity.

It uses visual hashing to find similar videos even if they have different formats/edits etc. It is slow, but it is accurate. 

## Installation

### Requirements

- Python 3.6+  
- OpenCV  
- Pillow (PIL)  
- NumPy  
- tqdm  
- colorama  
- imagehash  

### Install Dependencies

```
pipenv install
```

## Usage

### Basic

```
pipenv run python find_duplicates.py /path/to/videos
```

### Options

```
positional arguments:
  folder           Path to folder containing videos

optional arguments:
  -h, --help       Show help and exit
  --threshold N    Similarity threshold (default: 5.0; lower = stricter)
  --skip N         Number of frames to skip between keyframes (default: 30)
  --batch          Automatically keep the first file in duplicate pairs
  --move FOLDER    Move duplicates to this folder instead of deleting
```

### Examples

Stricter matching:
```
python video_deduplicator.py /path/to/videos --threshold 3.0
```

Batch mode:
```
python video_deduplicator.py /path/to/videos --batch
```

Move duplicates instead of deleting:
```
python video_deduplicator.py /path/to/videos --move /path/to/duplicates
```

Higher accuracy (slower):
```
python video_deduplicator.py /path/to/videos --skip 15
```

## How It Works

1. Extracts keyframes from videos  
2. Computes phash for frames  
3. Compares hashes
4. Flags videos below the threshold as duplicates
5. You do something

## Limitations
If a video is missing time from the front/middle of it, it probably won't pick it up as a duplicate. Video missing from the end is fine.

If you really wanted to you could slide the frames but it would ^x runtime

## Caching

I use a SQLite database (`video_hashes.db`) to store video fingerprints and speed up future scans.

## Supported Extensions

By default:
- .mp4, .mov, .avi, .mkv, .webm, .flv, .m4v

You can modify the `extensions` list in `get_video_files()` to support more.

## Troubleshooting

- **Can't open video**: Make sure you have codecs installed
- **Slow scans**: Increase the `--skip` value to process fewer frames, it is slow.
- **False matches/misses**: Adjust the `--threshold` value  