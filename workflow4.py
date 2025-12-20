import os
import json
import re
import praw
import prawcore
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv
from google import genai

# ==========================================
# 1. 配置与初始化
# ==========================================
load_dotenv()

# 检查环境
if not os.getenv("REDDIT_CLIENT_ID"):
    print("❌ Error: Missing Reddit credentials in .env")
    exit(1)

# API_KEY = os.environ.get("GOOGLE_API_KEY")
MODEL_ID = "gemini-3-flash-preview"

# 加载 Session ID (接续上下文)
try:
    with open("session_id.txt", "r") as f:
        SESSION_ID = f.read().strip()
    print(f"📂 Loaded Session ID: {SESSION_ID}")
except FileNotFoundError:
    print("❌ Error: 'session_id.txt' not found. Run Phase 1-3 first.")
    exit(1)

# 加载 Phase 3 选出的 Final Subreddits
try:
    with open("final_subreddits.json", "r") as f:
        target_subreddits = json.load(f)
    print(f"🎯 Loaded Target Subreddits: {target_subreddits}")
except FileNotFoundError:
    print("❌ Error: 'final_subreddits.json' not found. Run Phase 3 first.")
    exit(1)

reddit = praw.Reddit(
    client_id=os.getenv("REDDIT_CLIENT_ID"),
    client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
    user_agent=f"script:content_generation:v4.0 (by /u/{os.getenv('REDDIT_USERNAME', 'bot')})",
    username=os.getenv("REDDIT_USERNAME"),
    password=os.getenv("REDDIT_PASSWORD"),
)

client = genai.Client()

# ==========================================
# 2. 辅助函数：评论树抓取 (Token 优化版)
# ==========================================

def get_comment_tree_text(submission, limit_top_level=3, max_depth=1):
    """
    抓取指定帖子的评论树，返回格式化的字符串。
    为了节省 Token，默认只抓前 3 条一级评论，深度为 1。
    """
    buffer = ""
    
    # 这一步是为了消除 "MoreComments" 对象，防止报错，但限制加载数量以提速
    submission.comments.replace_more(limit=0)
    
    # 获取顶层评论
    top_level_comments = submission.comments[:limit_top_level]
    
    if not top_level_comments:
        return "   (No comments found)"

    for i, comment in enumerate(top_level_comments, 1):
        try:
            author = comment.author.name if comment.author else "[Deleted]"
            body = comment.body.replace('\n', ' ')[:200] # 限制单条评论长度
            
            # Level 0 (Root)
            buffer += f"   [C{i}] {author} (Score: {comment.score}): {body}\n"
            
            # Level 1 (Replies) - 只有当 max_depth >= 1 时才抓取
            if max_depth >= 1 and len(comment.replies) > 0:
                for reply in comment.replies[:2]: # 每个评论只看前2个回复
                    r_author = reply.author.name if reply.author else "[Deleted]"
                    r_body = reply.body.replace('\n', ' ')[:150]
                    buffer += f"      └─ {r_author}: {r_body}\n"
        except Exception:
            continue
            
    return buffer

# ==========================================
# 3. 辅助函数：KPI 计算 (流量阈值)
# ==========================================

def calculate_kpi_metrics(post_iterator, limit=15):
    """计算前 N 个帖子的平均指标 (跳过置顶)"""
    upvotes = []
    comments = []
    for post in post_iterator:
        if post.stickied: continue
        upvotes.append(post.score)
        comments.append(post.num_comments)
        if len(upvotes) >= limit: break
    
    if not upvotes: return 0, 0
    return int(sum(upvotes)/len(upvotes)), int(sum(comments)/len(comments))

# ==========================================
# 4. 核心逻辑：数据挖掘与组装
# ==========================================

def mine_subreddit_data(sub_list):
    print(f"\n🚀 Starting Deep Dive Analysis for {len(sub_list)} subreddits...\n")
    
    # AI Context Buffer: 最终发给 Gemini 的大字符串
    ai_buffer = "Here is the Deep Dive Data (Metrics + Style References) for the selected subreddits:\n\n"
    
    # 用于导出 KPI 表格的数据
    kpi_export_data = []

    for idx, sub_name in enumerate(sub_list, 1):
        print(f"[{idx}/{len(sub_list)}] Mining r/{sub_name}...", end="", flush=True)
        
        try:
            subreddit = reddit.subreddit(sub_name)
            
            # --- Part A: KPI Calculation (流量门槛) ---
            # 计算 Hot, Week, Month 的 赞/评 双指标
            hot_up, hot_com = calculate_kpi_metrics(subreddit.hot(limit=25))
            week_up, week_com = calculate_kpi_metrics(subreddit.top(time_filter="week", limit=25))
            month_up, month_com = calculate_kpi_metrics(subreddit.top(time_filter="month", limit=25))
            
            # 计算互动率 (Engagement Ratio): 评论数 / 点赞数
            # > 0.1 通常意味着高讨论度；< 0.05 意味着主要是看图/新闻
            eng_ratio = round(hot_com / hot_up, 3) if hot_up > 0 else 0
            
            # 计算 "长尾难度系数" (Month / Hot)
            # 如果倍数很大（如10倍），说明只有极少数精品能留存，竞争极残酷
            retention_multiplier = round(month_up / hot_up, 1) if hot_up > 0 else 0

            # 记录到 Excel 数据 (保存给人看)
            kpi_export_data.append({
                "Subreddit": sub_name,
                "Hot_Avg_Upvotes": hot_up,
                "Hot_Avg_Comments": hot_com,
                "TopWeek_Avg_Upvotes": week_up,
                "TopMonth_Avg_Upvotes": month_up,
                "Engagement_Ratio": eng_ratio
            })

            # --- 🌟 核心修改：写入更丰富的 AI Buffer ---
            ai_buffer += f"### TARGET SUBREDDIT: r/{sub_name}\n"
            ai_buffer += f"**PART 1: TRAFFIC & DIFFICULTY METRICS**\n"
            
            # 1. 基础门槛
            ai_buffer += f"- **Entry Level (Hot)**: Needs ~{hot_up} upvotes & ~{hot_com} comments to trend.\n"
            
            # 2. 互动偏好 (AI 需要这个来决定是写争议性观点还是发漂亮图)
            ai_buffer += f"- **Engagement Style**: Ratio is {eng_ratio}. "
            if eng_ratio > 0.15:
                ai_buffer += "(High Discussion: Users love to argue/comment. Text posts work best.)\n"
            elif eng_ratio < 0.05:
                ai_buffer += "(Lurker Heavy: Users vote but rarely comment. Needs high visual impact/images.)\n"
            else:
                ai_buffer += "(Balanced: Mix of consumption and discussion.)\n"

            # 3. 留存难度 (天花板)
            ai_buffer += f"- **Viral Ceiling (Top of Month)**: ~{month_up} upvotes.\n"
            ai_buffer += f"- **Difficulty Multiplier**: Top posts are {retention_multiplier}x bigger than Hot posts. "
            if retention_multiplier > 10:
                ai_buffer += "(EXTREME Difficulty: Content dies fast unless it's a masterpiece.)\n"
            else:
                ai_buffer += "(Moderate Stability: Good content stays visible longer.)\n\n"

            # --- Part B: Content Style References (保持不变) ---
            ai_buffer += f"**PART 2: STYLE REFERENCE (Top 3 Posts from this Month)**\n"
            top_posts = subreddit.top(time_filter="month", limit=10)
            count = 0
            for post in top_posts:
                if post.stickied: continue
                count += 1
                if count > 3: break 
                
                comment_tree_str = get_comment_tree_text(post, limit_top_level=3, max_depth=1)
                selftext = post.selftext.replace('\n', ' ')
                if len(selftext) > 400: selftext = selftext[:400] + "...(truncated)"
                if not selftext: selftext = "[Image/Link Post Only]"

                ai_buffer += f"--- Ref Post #{count} ---\n"
                ai_buffer += f"Title: {post.title}\n"
                ai_buffer += f"Body: {selftext}\n"
                ai_buffer += f"Comments Vibe:\n{comment_tree_str}\n"
            
            ai_buffer += "="*40 + "\n\n"
            print(" ✅ Done")

        except Exception as e:
            print(f" ❌ Error ({e})")
            ai_buffer += f"### r/{sub_name}: Error scraping data ({e})\n\n"

    # 导出 KPI 到 Excel
    if kpi_export_data:
        df = pd.DataFrame(kpi_export_data)
        filename = f"Phase4_KPI_Analysis_{datetime.now().strftime('%Y%m%d')}.xlsx"
        df.to_excel(filename, index=False)
        print(f"\n📊 KPI Data saved to: {filename}")
    
    return ai_buffer

# ==========================================
# 5. Gemini 生成逻辑
# ==========================================

def run_phase4_generation(context_data):
    print("\n🤖 Sending mined data to Gemini for Final Content Drafting...")

    PHASE4_PROMPT = f"""
{context_data}

### TASK: Phase 4 - Content Creation & KPI Strategy

You are the "Reddit Ghostwriter". Above is the REAL data (KPIs + Style References) for our target subreddits.
Your goal is to maximize the probability of our product (from Phase 1 context) trending in these communities.

**Requirement 1: The Strategic Analysis Table & Legend**
1. **The Table**: Create a comprehensive Markdown table using the "Traffic & Difficulty Metrics" provided.
   - **Columns**:
     1. **Subreddit**
     2. **Difficulty Score**: (Assess based on the "Viral Ceiling" and "Difficulty Multiplier").
     3. **Engagement Type**: (Based on the "Engagement Ratio" provided in metrics - e.g., "High Debate", "Visual/Lurker", "Balanced").
     4. **Content Strategy Note**: **CRITICAL**. Do NOT give generic advice. 
        - If "Engagement Type" is High Debate -> Suggest a controversial title or a question.
        - If "Engagement Type" is Visual -> Suggest a UI screenshot or meme format.
        - If "Difficulty Multiplier" is high -> Emphasize that the content must be "Best of Month" quality to survive.

2. **Methodology (The Formulas)**: 
   Immediately following the table, add a compact section titled "**KPI Methodology**". Display the algorithm formulas used to derive the metrics. Keep explanations strictly concise and academic. 
   **Format Requirements**:
   - **Engagement Index ($E$)**: Formula: `Avg. Comments / Avg. Upvotes`. *Indicates community interaction depth.*
   - **Viral Ceiling ($V$)**: Formula: `Top(Month)_avg / Hot_avg`. *Measures the volatility barrier for long-term retention.*

**Requirement 2: Native Content Drafting (The Core)**
For EACH of the target subreddits, write a tailored draft.
* **Format**: Determine if it should be a Text Post or a Link/Image Post based on the reference data.
* **Title**: Must be click-worthy but NOT clickbait. Use the linguistic style of that sub (e.g., lowercase for tech subs, formal for academic subs).
* **Body**: Write the full post body. **Do not be salesy.** Use the "Trojan Horse" technique: provide 80% value/story/insight, and mention the product only as a natural part of the solution (20%).
* **Seeding Comments**: Write 3-5 distinct comments that we can use to "seed" the discussion. These should look like genuine user questions or reactions (e.g., "Skeptical but interested", "Asking about privacy", "Joke about the problem").
    * *Format*: Display these as a simulated comment tree (e.g., User A asks -> User B answers).

**Output Format**:
Please structure the response clearly with Markdown headers for each Subreddit.
"""

    try:
        interaction = client.interactions.create(
            model=MODEL_ID,
            previous_interaction_id=SESSION_ID,
            input=PHASE4_PROMPT,
        )

        full_response = interaction.outputs[-1].text
        
        # 保存最终报告
        with open("project_final_content_plan.md", "w", encoding="utf-8") as f:
            f.write(full_response)
        
        print("\n" + "="*50)
        print("🎉🎉🎉 WORKFLOW COMPLETE! 🎉🎉🎉")
        print("📄 Final Report: 'project_final_content_plan.md'")
        print("="*50)

        # 更新 Session
        with open("session_id.txt", "w") as f:
            f.write(interaction.id)

    except Exception as e:
        print(f"❌ Gemini Error: {e}")

# ==========================================
# 6. 执行入口
# ==========================================

if __name__ == "__main__":
    # 1. 挖掘数据 (KPI + 风格)
    context_buffer = mine_subreddit_data(target_subreddits)
    
    # 2. 调用 AI 生成最终方案
    run_phase4_generation(context_buffer)