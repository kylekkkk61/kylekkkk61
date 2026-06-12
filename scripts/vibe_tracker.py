import os
import glob
import json
import sqlite3
import re
from datetime import datetime

README_PATH = os.path.expanduser('~/Downloads/kylekkkk61/README.md')
AG_BRAIN_DIR = os.path.expanduser('~/.gemini/antigravity/brain/')
CODEX_DB_PATH = os.path.expanduser('~/.codex/state_5.sqlite')

def get_antigravity_stats():
    transcripts = glob.glob(os.path.join(AG_BRAIN_DIR, '*', '.system_generated', 'logs', 'transcript.jsonl'))
    
    user_words = 0
    ai_words = 0
    command_count = 0
    total_seconds = 0
    
    for t_file in transcripts:
        first_time = None
        last_time = None
        
        with open(t_file, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    data = json.loads(line)
                    created_at_str = data.get('created_at')
                    if created_at_str:
                        # Parse time, e.g., 2026-06-12T07:16:05Z
                        t = datetime.strptime(created_at_str, "%Y-%m-%dT%H:%M:%SZ")
                        if first_time is None:
                            first_time = t
                        last_time = t
                        
                    if data.get('type') == 'USER_INPUT':
                        content = data.get('content', '')
                        user_words += len(content.split())
                        command_count += 1
                    elif data.get('type') == 'MODEL' or data.get('source') == 'MODEL':
                        content = data.get('content', '')
                        thinking = data.get('thinking', '')
                        ai_words += len(content.split()) + len(thinking.split())
                except Exception:
                    pass
        
        if first_time and last_time:
            diff = (last_time - first_time).total_seconds()
            if diff > 0:
                total_seconds += diff
                
    # Estimation: 1 word approx 1.3 tokens
    user_tokens = int(user_words * 1.3)
    ai_tokens = int(ai_words * 1.3)
    
    return {
        'command_count': command_count,
        'user_tokens': user_tokens,
        'ai_tokens': ai_tokens,
        'total_seconds': total_seconds
    }

def get_codex_stats():
    if not os.path.exists(CODEX_DB_PATH):
        return {
            'command_count': 0,
            'user_tokens': 0,
            'ai_tokens': 0,
            'total_seconds': 0
        }
        
    try:
        conn = sqlite3.connect(CODEX_DB_PATH)
        cursor = conn.cursor()
        
        # count(*), sum(tokens_used), sum(updated_at - created_at)
        cursor.execute("SELECT count(*), sum(tokens_used), sum(updated_at - created_at) FROM threads;")
        row = cursor.fetchone()
        conn.close()
        
        if row and row[0]:
            total_commands = row[0]
            total_tokens = row[1] or 0
            total_seconds = row[2] or 0
            
            # Assume Codex output tokens are ~80% of total, input is ~20%
            ai_tokens = int(total_tokens * 0.8)
            user_tokens = int(total_tokens * 0.2)
            
            return {
                'command_count': total_commands,
                'user_tokens': user_tokens,
                'ai_tokens': ai_tokens,
                'total_seconds': total_seconds
            }
    except Exception as e:
        print(f"Error reading Codex DB: {e}")
        
    return {
        'command_count': 0,
        'user_tokens': 0,
        'ai_tokens': 0,
        'total_seconds': 0
    }

def generate_ascii_bar(ai_val, user_val, length=24):
    total = ai_val + user_val
    if total == 0:
        return "░" * length, 0.0, 0.0
        
    ai_ratio = ai_val / total
    ai_blocks = int(round(ai_ratio * length))
    user_blocks = length - ai_blocks
    
    bar = ("█" * ai_blocks) + ("░" * user_blocks)
    return bar, ai_ratio * 100, (1 - ai_ratio) * 100

def format_time(seconds):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    return f"{hours} hrs {minutes} mins"

def format_number(num):
    if num >= 1_000_000:
        return f"{num/1_000_000:.1f}M"
    elif num >= 1_000:
        return f"{num/1_000:.1f}K"
    return str(num)

def update_readme(stats_text):
    if not os.path.exists(README_PATH):
        print(f"README not found at {README_PATH}")
        return
        
    with open(README_PATH, 'r', encoding='utf-8') as f:
        content = f.read()
        
    pattern = r'(<!--START_SECTION:vibe-->).*?(<!--END_SECTION:vibe-->)'
    
    # Check if section exists
    if not re.search(pattern, content, re.DOTALL):
        # Append to end if not exists
        content += f"\n<!--START_SECTION:vibe-->\n{stats_text}\n<!--END_SECTION:vibe-->\n"
    else:
        # Replace existing
        replacement = f"\\1\n{stats_text}\n\\2"
        content = re.sub(pattern, replacement, content, flags=re.DOTALL)
        
    with open(README_PATH, 'w', encoding='utf-8') as f:
        f.write(content)
        
    print("README.md updated successfully!")

def main():
    ag_stats = get_antigravity_stats()
    codex_stats = get_codex_stats()
    
    total_commands = ag_stats['command_count'] + codex_stats['command_count']
    total_user_tokens = ag_stats['user_tokens'] + codex_stats['user_tokens']
    total_ai_tokens = ag_stats['ai_tokens'] + codex_stats['ai_tokens']
    total_seconds = ag_stats['total_seconds'] + codex_stats['total_seconds']
    
    bar, ai_pct, user_pct = generate_ascii_bar(total_ai_tokens, total_user_tokens)
    
    # Calculate percentages for Top Agents
    total_tokens_all = total_ai_tokens + total_user_tokens
    if total_tokens_all > 0:
        ag_total = ag_stats['ai_tokens'] + ag_stats['user_tokens']
        codex_total = codex_stats['ai_tokens'] + codex_stats['user_tokens']
        ag_pct = int((ag_total / total_tokens_all) * 100)
        codex_pct = int((codex_total / total_tokens_all) * 100)
    else:
        ag_pct = 0
        codex_pct = 0
    
    output = f"""```text
🤖 Vibe Coding Stats (All Time)

Total Command Time: {format_time(total_seconds)}
Decisions Made (Prompts Sent): {total_commands}

Token Usage & Generation:
AI Generated   {format_number(total_ai_tokens):>6} tokens  {bar}   {ai_pct:05.2f} %
Human Typed    {format_number(total_user_tokens):>6} tokens  {bar.replace('█', '▓').replace('░', '█').replace('▓', '░')}   {user_pct:05.2f} %

Top Agents: Codex ({codex_pct}%), Antigravity ({ag_pct}%)
```"""
    
    print(output)
    update_readme(output)

if __name__ == '__main__':
    main()
