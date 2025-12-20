import os
import json
import re
import glob
import praw
import prawcore
import pandas as pd
import datetime
from dotenv import load_dotenv
from google import genai

# ==========================================
# 1. 配置与鉴权
# ==========================================
load_dotenv()
MODEL_ID = "gemini-3-flash-preview"
TIMESTAMP = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def load_prompts() -> dict[str, str]:
    """Load per-run prompts from PROMPTS_FILE (JSON), if provided."""
    prompts_file = os.environ.get("PROMPTS_FILE")
    if not prompts_file:
        return {}

    try:
        with open(prompts_file, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            return {}
        return {k: v for k, v in raw.items() if isinstance(k, str) and isinstance(v, str)}
    except Exception as e:
        print(f"?? Warning: Failed to load PROMPTS_FILE='{prompts_file}': {e}")
        return {}


def render_prompt(template: str, *, rules_context: str) -> str:
    return template.replace("{{rules_context}}", rules_context)


PROMPTS = load_prompts()

if not os.getenv("REDDIT_CLIENT_ID"):
    print("❌ Error: Missing Reddit credentials in .env")
    exit(1)

# Helper: Find latest file
def get_latest_file(pattern):
    files = glob.glob(pattern)
    return max(files, key=os.path.getctime) if files else None

# [MODIFIED] Load LATEST Phase 2 Session ID
try:
    latest_session_file = get_latest_file("session_id_phase2_*.txt")
    if not latest_session_file: raise FileNotFoundError("No 'session_id_phase2_*.txt' found.")
    
    with open(latest_session_file, "r") as f:
        SESSION_ID = f.read().strip()
    print(f"📂 Loaded Session ID from: {latest_session_file}")
except Exception as e:
    print(f"❌ Error: {e}")
    exit(1)

# [MODIFIED] Load LATEST Raw Subreddit JSON
try:
    latest_json_file = get_latest_file("raw_subreddits_*.json")
    if not latest_json_file: raise FileNotFoundError("No 'raw_subreddits_*.json' found.")

    with open(latest_json_file, "r") as f:
        target_subreddits = json.load(f)
    print(f"📋 Loaded {len(target_subreddits)} subreddits from: {latest_json_file}")
except Exception as e:
    print(f"❌ Error: {e}")
    exit(1)

# Initialize Clients
reddit = praw.Reddit(
    client_id=os.getenv("REDDIT_CLIENT_ID"),
    client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
    user_agent=f"script:market_research:v2.0 (by /u/{os.getenv('REDDIT_USERNAME', 'bot')})",
    username=os.getenv("REDDIT_USERNAME"),
    password=os.getenv("REDDIT_PASSWORD"),
)

client = genai.Client()

# ==========================================
# 2. PRAW 数据抓取与格式化
# ==========================================

def fetch_and_format_rules(sub_list):
    print(f"\n🚀 Starting PRAW Analysis for {len(sub_list)} communities...\n")
    
    excel_data = []
    
    # 🌟 AI Buffer: 专门构建给大模型看的纯文本字符串
    ai_context_buffer = "Here is the detailed Rules & Data report for the proposed subreddits:\n\n"

    for index, sub_name in enumerate(sub_list, 1):
        print(f"[{index}/{len(sub_list)}] Scanning r/{sub_name}...", end="", flush=True)
        
        row = {
            "Subreddit": sub_name,
            "URL": f"https://www.reddit.com/r/{sub_name}/",
            "Subscribers": 0,
            "Status": "",
            "Has_Rules": "No",
            "Rules_Raw": ""
        }

        # 🌟 构建单条 Subreddit 的 AI 描述块
        sub_ai_block = f"### Subreddit: r/{sub_name}\n"
        
        try:
            subreddit = reddit.subreddit(sub_name)
            
            # 1. 流量数据
            subs_count = subreddit.subscribers
            row["Subscribers"] = subs_count
            
            # 2. 状态检查
            sub_ai_block += f"- Status: Active\n"
            sub_ai_block += f"- Subscribers: {subs_count}\n"
            sub_ai_block += f"- Rules:\n"

            # 3. 版规获取
            rule_list = list(subreddit.rules)
            row["Status"] = "Active"

            if rule_list:
                row["Has_Rules"] = "Yes"
                formatted_rules_excel = []
                
                for idx, rule in enumerate(rule_list, 1):
                    title = getattr(rule, 'short_name', 'No Title')
                    desc = getattr(rule, 'description', '')
                    
                    # Excel 格式 (紧凑)
                    formatted_rules_excel.append(f"{idx}. {title}")
                    
                    # AI 格式 (优化阅读，带缩进和空行)
                    sub_ai_block += f"  {idx}. {title}\n"
                    if desc:
                        # 清洗描述中的过多换行，保持整洁
                        clean_desc = desc.strip().replace('\n', ' ')
                        # 截断过长的描述以节省 Token (可选)
                        if len(clean_desc) > 300: 
                            clean_desc = clean_desc[:300] + "..."
                        sub_ai_block += f"     Description: {clean_desc}\n\n" # 规则间增加空行
                    else:
                        sub_ai_block += "\n" # 无描述也换行

                row["Rules_Raw"] = "\n".join(formatted_rules_excel)
            else:
                sub_ai_block += "  (No structured rules found)\n"
                row["Rules_Raw"] = "None"
            
            print(" ✅")

        except prawcore.exceptions.NotFound:
            row["Status"] = "404 Not Found"
            sub_ai_block += "- Status: Does Not Exist (404)\n"
            print(" ❌ (404)")
        except prawcore.exceptions.Forbidden:
            row["Status"] = "403 Forbidden"
            sub_ai_block += "- Status: Private/Banned (403)\n"
            print(" 🚫 (403)")
        except Exception as e:
            row["Status"] = f"Error: {str(e)}"
            sub_ai_block += f"- Status: Error ({str(e)})\n"
            print(f" ⚠️ ({e})")

        excel_data.append(row)
        
        # 将该块加入总 Buffer，并增加显著的分隔符
        ai_context_buffer += sub_ai_block
        ai_context_buffer += "\n" + "-"*40 + "\n\n"

    # [MODIFIED] Export Excel with Timestamp
    df = pd.DataFrame(excel_data).sort_values(by="Subscribers", ascending=False)
    excel_filename = f"Phase3_Subreddit_Audit_{TIMESTAMP}.xlsx"
    df.to_excel(excel_filename, index=False)
    print(f"\n💾 Excel Audit Report saved: {excel_filename}")

    return ai_context_buffer

# ==========================================
# 3. Gemini 回环: 筛选与报告生成
# ==========================================

def run_phase3_filter(rules_context):
    print("\n🤖 Sending PRAW data back to Gemini for Phase 3 filtering...")

    PHASE3_PROMPT = f"""
{rules_context}

### TASK: Phase 3 - Filtering & Strategy (The Pivot)

You have just received the REAL-WORLD audit data (above) for the subreddits you brainstormed.
Some may not exist, some may be too small, and some may have strict rules against self-promotion.

**Please perform the following:**

1.  **The Filter Logic**: Briefly explain your filtering criteria based on the data (e.g., removing banned subs, avoiding subs with "No Ads" rules unless we use a specific strategy, prioritizing high traffic).
2.  **The Final Selection**: Select the **Top 5** most promising subreddits from the list above.
3.  **Section 2 of the Marketing Plan**: Write the "Community Strategy" section. For EACH of the 5 selected subreddits, explain:
    * **Why selected**: (Traffic + Relevance)
    * **The Angle**: How to approach it without violating its specific rules (Reference the specific rule number if applicable).

**IMPORTANT**:
At the very end, output the names of the Final 5 subreddits in a STRICT JSON ARRAY for the next script.
Example:
```json
["productivity", "webdev", "SaaS", "SideProject", "coding"]

```
"""

    try:
        override_template = PROMPTS.get("phase3_prompt")
        phase3_prompt = (
            render_prompt(override_template, rules_context=rules_context) if override_template else PHASE3_PROMPT
        )

        interaction = client.interactions.create(
            model=MODEL_ID,
            previous_interaction_id=SESSION_ID,
            input=phase3_prompt,
        )

        full_response = interaction.outputs[-1].text
        
        # 1. Save JSON
        json_match = re.search(r"```json\s*(\[.*?\])\s*```", full_response, re.DOTALL)
        if json_match:
            final_list = json.loads(json_match.group(1))
            
            # [MODIFIED] Save Final JSON with Timestamp
            final_json_filename = f"final_subreddits_{TIMESTAMP}.json"
            with open(final_json_filename, "w") as f:
                json.dump(final_list, f, indent=4)
            print(f"📦 [File Created] '{final_json_filename}' with {len(final_list)} targets.")
        
        # 2. Save Report
        report_text = re.sub(r"```json\s*\[.*?\]\s*```", "", full_response, flags=re.DOTALL).strip()
        
        # [MODIFIED] Save Strategy Report with Timestamp
        strategy_filename = f"project_part2_strategy_{TIMESTAMP}.md"
        with open(strategy_filename, "w", encoding="utf-8") as f:
            f.write(report_text)
        print(f"📄 [File Created] '{strategy_filename}'.")

        # [MODIFIED] Save Session ID for Phase 3
        new_session_filename = f"session_id_phase3_{TIMESTAMP}.txt"
        with open(new_session_filename, "w") as f:
            f.write(interaction.id)
        print(f"🔗 [Session Updated] Saved to '{new_session_filename}'")

    except Exception as e:
        print(f"❌ Gemini Error: {e}")



# ==========================================

# 4. 执行

# ==========================================

if __name__ == "__main__":
    # 1. 抓取数据并格式化成 AI 易读文本
    context_data = fetch_and_format_rules(target_subreddits)

    # 2. 发送给 Gemini 进行决策
    run_phase3_filter(context_data)


'''
### 🧠 代码优化点解析
1.  **AI Buffer 格式化**:
    * 如果你看代码里的 `sub_ai_block` 部分，我特意在 Description 后加了 `\n\n`。
    * 我还在每个 Subreddit 之间加了 `"-"*40` 分隔线。这对于 LLM 来说非常友好，它能清楚地知道“上一个社区的规则到此结束，下一个开始了”。
2.  **JSON 传递**:
    * 脚本读取 `raw_subreddits.json` (30+个)。
    * 脚本输出 `final_subreddits.json` (5个)。这是一个完美的漏斗结构。

### 👉 你的任务
1.  **确保** `.env` 里配置了 `REDDIT_CLIENT_ID` 等信息。
2.  **运行** `workflow_phase3.py`。
3.  这个过程可能会花几十秒（因为要抓取30个sub），请耐心等待。
4.  运行结束后，检查文件夹，你应该会看到：
    * `Phase3_Subreddit_Audit_2025xxxx.xlsx` (Excel 报告)
    * `project_part2_strategy.md` (策略报告)
    * `final_subreddits.json` (最终选定的5个Sub)

如果这一步成功，我们就只剩下最后一步 **Phase 4：爬取热帖与文案生成** 了！等你确认！

'''
