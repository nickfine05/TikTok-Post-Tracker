"""
Server-Specific Creator Channel Tracking Bot
Tracks posts separately for each Discord server
"""

import discord
from discord.ext import commands, tasks
import json
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

# Configuration
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
REMINDER_DAYS = 2  # Remind every 2 days if they haven't posted
DATA_FILE = 'server_tracking.json'

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True
bot = commands.Bot(command_prefix='!', intents=intents)

# ================== DATA MANAGEMENT ==================

def load_data():
    """Load tracking data"""
    try:
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    except:
        return {
            'tracked_channels': {},  # channel_id: {creator_id, guild_id, creator_name}
            'creators': {},  # guild_id_creator_id: creator data
            'posts': {},    # guild_id_creator_id: post data
        }

def save_data(data):
    """Save tracking data"""
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2, default=str)

# ================== BOT EVENTS ==================

@bot.event
async def on_ready():
    print(f"""
    ╔════════════════════════════════════╗
    ║   Server-Specific Tracker          ║
    ║   Separate tracking per server     ║
    ╚════════════════════════════════════╝
    
    Logged in as: {bot.user}
    Active in {len(bot.guilds)} servers
    
    Commands:
    !setup @creator - Setup in this channel
    !dashboard - View this server's creators
    !stats @user - Individual stats for this server
    """)
    
    # Start background tasks
    check_reminders.start()

@bot.event
async def on_message(message):
    """Track posted messages in registered channels"""
    
    # Ignore bot messages
    if message.author.bot:
        return
    
    # Ignore DMs
    if not message.guild:
        return
    
    data = load_data()
    
    # Get server and channel IDs
    guild_id = str(message.guild.id)
    channel_id = str(message.channel.id)
    
    # Check if this channel is being tracked
    if channel_id in data['tracked_channels']:
        # Check for posted message
        posted_keywords = ['posted', 'done', 'uploaded', 'posted for today', 'posted today']
        
        if any(keyword in message.content.lower() for keyword in posted_keywords):
            
            # Get the creator info for this channel
            channel_data = data['tracked_channels'][channel_id]
            creator_id = channel_data['creator_id']
            creator_name = channel_data['creator_name']
            
            # Create unique key for this server+creator combination
            unique_key = f"{guild_id}_{creator_id}"
            
            today = datetime.now().strftime('%Y-%m-%d')
            timestamp = datetime.now().isoformat()
            
            # Initialize creator if new (server-specific)
            if unique_key not in data['creators']:
                data['creators'][unique_key] = {
                    'name': creator_name,
                    'guild_id': guild_id,
                    'guild_name': message.guild.name,
                    'creator_id': creator_id,
                    'channel_id': channel_id,
                    'joined': today,
                    'total_posts': 0,
                    'current_streak': 0,
                    'best_streak': 0,
                    'last_posted': None,
                    'last_reminded': None
                }
            
            # Check if already posted today
            if unique_key not in data['posts']:
                data['posts'][unique_key] = {}
            
            if today not in data['posts'][unique_key]:
                # Record the post
                data['posts'][unique_key][today] = {
                    'timestamp': timestamp,
                    'channel': message.channel.name,
                    'guild': message.guild.name
                }
                
                # Update creator stats
                data['creators'][unique_key]['total_posts'] += 1
                data['creators'][unique_key]['last_posted'] = today
                data['creators'][unique_key]['name'] = creator_name  # Update name in case it changed
                
                # Calculate streak
                yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
                if yesterday in data['posts'][unique_key]:
                    data['creators'][unique_key]['current_streak'] += 1
                else:
                    data['creators'][unique_key]['current_streak'] = 1
                
                # Update best streak
                current = data['creators'][unique_key]['current_streak']
                best = data['creators'][unique_key]['best_streak']
                if current > best:
                    data['creators'][unique_key]['best_streak'] = current
                
                save_data(data)
                
                # React to confirm
                await message.add_reaction('✅')
                
                # Send confirmation
                week_count = get_posts_in_period(unique_key, 7)
                month_count = get_posts_in_period(unique_key, 30)
                
                embed = discord.Embed(
                    title="✅ Post Tracked!",
                    color=discord.Color.green()
                )
                embed.add_field(name="Server", value=message.guild.name, inline=True)
                embed.add_field(name="Streak", value=f"🔥 {current} days", inline=True)
                embed.add_field(name="Week", value=f"{week_count}/7", inline=True)
                embed.add_field(name="Month", value=f"{month_count} posts", inline=True)
                
                await message.channel.send(embed=embed)
                
            else:
                # Already posted today
                await message.reply("Already tracked your post for today in this server! 👍", mention_author=False)
    
    # Process commands
    await bot.process_commands(message)

# ================== SETUP COMMANDS ==================

@bot.command(name='setup')
@commands.has_permissions(manage_channels=True)
async def setup_channel(ctx, member: discord.Member):
    """Setup tracking for a creator in this channel (server-specific)"""
    data = load_data()
    
    channel_id = str(ctx.channel.id)
    creator_id = str(member.id)
    guild_id = str(ctx.guild.id)
    
    # Check if channel already tracked
    if channel_id in data['tracked_channels']:
        current_creator = data['tracked_channels'][channel_id]['creator_name']
        embed = discord.Embed(
            title="Channel Already Setup",
            description=f"This channel is tracking **{current_creator}**\nUse `!unsetup` first to change.",
            color=discord.Color.orange()
        )
        await ctx.send(embed=embed)
        return
    
    # Setup the channel with server info
    data['tracked_channels'][channel_id] = {
        'creator_id': creator_id,
        'creator_name': member.name,
        'guild_id': guild_id,
        'guild_name': ctx.guild.name,
        'setup_by': str(ctx.author.id),
        'setup_date': datetime.now().strftime('%Y-%m-%d')
    }
    
    # Create unique key for this server+creator
    unique_key = f"{guild_id}_{creator_id}"
    
    # Initialize creator if needed (server-specific)
    if unique_key not in data['creators']:
        data['creators'][unique_key] = {
            'name': member.name,
            'guild_id': guild_id,
            'guild_name': ctx.guild.name,
            'creator_id': creator_id,
            'channel_id': channel_id,
            'joined': datetime.now().strftime('%Y-%m-%d'),
            'total_posts': 0,
            'current_streak': 0,
            'best_streak': 0,
            'last_posted': None,
            'last_reminded': None
        }
    
    save_data(data)
    
    embed = discord.Embed(
        title="✅ Channel Setup Complete!",
        description=f"Now tracking **{member.name}** in this channel\nServer: **{ctx.guild.name}**",
        color=discord.Color.green()
    )
    embed.add_field(
        name="How it works",
        value=f"{member.mention} just needs to type 'posted' after uploading to TikTok",
        inline=False
    )
    embed.add_field(
        name="Important",
        value="Tracking is separate for each server - posts here won't count in other servers!",
        inline=False
    )
    
    await ctx.send(embed=embed)

@bot.command(name='unsetup')
@commands.has_permissions(manage_channels=True)
async def unsetup_channel(ctx):
    """Remove tracking from this channel"""
    data = load_data()
    
    channel_id = str(ctx.channel.id)
    
    if channel_id not in data['tracked_channels']:
        await ctx.send("This channel isn't being tracked.")
        return
    
    creator_name = data['tracked_channels'][channel_id]['creator_name']
    
    # Remove channel from tracking
    del data['tracked_channels'][channel_id]
    save_data(data)
    
    embed = discord.Embed(
        title="✅ Tracking Removed",
        description=f"No longer tracking **{creator_name}** in this channel",
        color=discord.Color.orange()
    )
    
    await ctx.send(embed=embed)

@bot.command(name='channels')
@commands.has_permissions(manage_channels=True)
async def list_channels(ctx):
    """List all tracked channels IN THIS SERVER"""
    data = load_data()
    guild_id = str(ctx.guild.id)
    
    # Filter channels for this server only
    server_channels = {
        ch_id: info for ch_id, info in data['tracked_channels'].items()
        if info.get('guild_id') == guild_id
    }
    
    if not server_channels:
        await ctx.send("No channels are being tracked in this server. Use `!setup @creator` in a channel to start.")
        return
    
    embed = discord.Embed(
        title=f"📍 Tracked Channels in {ctx.guild.name}",
        description=f"Tracking {len(server_channels)} channels in this server",
        color=discord.Color.blue()
    )
    
    for channel_id, info in server_channels.items():
        channel = bot.get_channel(int(channel_id))
        channel_name = channel.name if channel else "Unknown Channel"
        
        # Get creator data for this server
        unique_key = f"{guild_id}_{info['creator_id']}"
        creator_data = data['creators'].get(unique_key, {})
        last_post = creator_data.get('last_posted', 'Never')
        
        embed.add_field(
            name=f"#{channel_name}",
            value=f"Creator: **{info['creator_name']}**\nLast post: {last_post}",
            inline=True
        )
    
    await ctx.send(embed=embed)

# ================== TRACKING FUNCTIONS ==================

def get_posts_in_period(unique_key: str, days: int) -> int:
    """Get number of posts in last X days for a specific server+creator"""
    data = load_data()
    count = 0
    
    if unique_key in data['posts']:
        cutoff = datetime.now() - timedelta(days=days)
        
        for date_str in data['posts'][unique_key]:
            post_date = datetime.strptime(date_str, '%Y-%m-%d')
            if post_date >= cutoff:
                count += 1
    
    return count

# ================== BACKGROUND TASKS ==================

@tasks.loop(hours=12)
async def check_reminders():
    """Check and send reminders every 12 hours"""
    data = load_data()
    
    for unique_key, creator_info in data['creators'].items():
        last_posted = creator_info.get('last_posted')
        last_reminded = creator_info.get('last_reminded')
        
        if last_posted:
            days_since_post = (datetime.now() - datetime.strptime(last_posted, '%Y-%m-%d')).days
            
            # Send reminder if hasn't posted in REMINDER_DAYS
            if days_since_post >= REMINDER_DAYS:
                should_remind = True
                
                # Check if we already reminded recently
                if last_reminded:
                    days_since_reminder = (datetime.now() - datetime.strptime(last_reminded, '%Y-%m-%d')).days
                    if days_since_reminder < REMINDER_DAYS:
                        should_remind = False
                
                if should_remind:
                    try:
                        creator_id = creator_info['creator_id']
                        user = await bot.fetch_user(int(creator_id))
                        channel_id = creator_info.get('channel_id')
                        channel = bot.get_channel(int(channel_id)) if channel_id else None
                        
                        embed = discord.Embed(
                            title="📱 Posting Reminder",
                            description=f"You haven't posted in {days_since_post} days!",
                            color=discord.Color.orange()
                        )
                        
                        embed.add_field(
                            name="Server",
                            value=creator_info.get('guild_name', 'Unknown'),
                            inline=True
                        )
                        
                        if channel:
                            embed.add_field(
                                name="Your Channel",
                                value=f"Post 'posted' in {channel.mention} when done!",
                                inline=False
                            )
                        
                        embed.add_field(
                            name="Last Post",
                            value=last_posted,
                            inline=True
                        )
                        
                        await user.send(embed=embed)
                        
                        # Update last reminded
                        data['creators'][unique_key]['last_reminded'] = datetime.now().strftime('%Y-%m-%d')
                        save_data(data)
                        
                    except:
                        pass  # Can't DM user

# ================== REPORTING COMMANDS ==================

@bot.command(name='dashboard')
async def dashboard(ctx):
    """Show dashboard for THIS SERVER ONLY"""
    data = load_data()
    guild_id = str(ctx.guild.id)
    
    # Filter creators for this server only
    server_creators = {
        key: info for key, info in data['creators'].items()
        if info.get('guild_id') == guild_id
    }
    
    if not server_creators:
        await ctx.send("No creators being tracked in this server! Use `!setup @creator` in their channel.")
        return
    
    embed = discord.Embed(
        title=f"📊 {ctx.guild.name} Dashboard",
        description=f"Tracking {len(server_creators)} creators in this server",
        color=discord.Color.blue(),
        timestamp=datetime.now()
    )
    
    # Sort by most recent posts
    sorted_creators = sorted(
        server_creators.items(),
        key=lambda x: x[1].get('last_posted', ''),
        reverse=True
    )
    
    for unique_key, info in sorted_creators[:20]:  # Discord embed limit
        week_posts = get_posts_in_period(unique_key, 7)
        
        # Status emoji
        last_posted = info.get('last_posted', 'Never')
        if last_posted != 'Never':
            days_since = (datetime.now() - datetime.strptime(last_posted, '%Y-%m-%d')).days
            if days_since == 0:
                status = "✅"
            elif days_since <= 1:
                status = "⚠️"
            else:
                status = "❌"
        else:
            status = "❓"
        
        embed.add_field(
            name=f"{status} {info['name']}",
            value=f"Week: {week_posts}/7 | Streak: 🔥{info['current_streak']}\nLast: {last_posted}",
            inline=False
        )
    
    embed.set_footer(text=f"Data for {ctx.guild.name} only")
    await ctx.send(embed=embed)

@bot.command(name='weekly')
async def weekly_report(ctx):
    """Get weekly report FOR THIS SERVER"""
    data = load_data()
    guild_id = str(ctx.guild.id)
    
    # Filter for this server
    server_creators = {
        key: info for key, info in data['creators'].items()
        if info.get('guild_id') == guild_id
    }
    
    if not server_creators:
        await ctx.send("No creators to report on in this server!")
        return
    
    embed = discord.Embed(
        title=f"📅 Weekly Report - {ctx.guild.name}",
        description=f"Performance for the last 7 days",
        color=discord.Color.green()
    )
    
    total_posts = 0
    perfect_week = []
    needs_improvement = []
    
    for unique_key, info in server_creators.items():
        week_posts = get_posts_in_period(unique_key, 7)
        total_posts += week_posts
        
        if week_posts >= 7:
            perfect_week.append(info['name'])
        elif week_posts < 3:
            needs_improvement.append(f"{info['name']} ({week_posts}/7)")
    
    # Summary stats
    active_creators = len([c for key, c in server_creators.items() if get_posts_in_period(key, 7) > 0])
    
    embed.add_field(
        name="📊 Overview",
        value=f"Total Posts: {total_posts}\nActive Creators: {active_creators}/{len(server_creators)}\nAvg/Creator: {total_posts/len(server_creators) if server_creators else 0:.1f}",
        inline=False
    )
    
    if perfect_week:
        embed.add_field(
            name="🌟 Perfect Week (7/7)",
            value="\n".join(perfect_week[:10]),
            inline=True
        )
    
    if needs_improvement:
        embed.add_field(
            name="⚠️ Needs Improvement",
            value="\n".join(needs_improvement[:10]),
            inline=True
        )
    
    embed.set_footer(text=f"Server-specific data for {ctx.guild.name}")
    await ctx.send(embed=embed)

@bot.command(name='stats')
async def individual_stats(ctx, member: discord.Member = None):
    """Get individual creator stats FOR THIS SERVER"""
    if member is None:
        member = ctx.author
    
    data = load_data()
    guild_id = str(ctx.guild.id)
    creator_id = str(member.id)
    unique_key = f"{guild_id}_{creator_id}"
    
    if unique_key not in data['creators']:
        await ctx.send(f"No tracking data for {member.mention} in this server. They need to be set up with `!setup @{member.name}`")
        return
    
    info = data['creators'][unique_key]
    
    embed = discord.Embed(
        title=f"📊 Stats for {member.name} in {ctx.guild.name}",
        color=discord.Color.gold()
    )
    
    # Calculate stats
    week_posts = get_posts_in_period(unique_key, 7)
    month_posts = get_posts_in_period(unique_key, 30)
    
    embed.add_field(name="Server", value=ctx.guild.name, inline=False)
    embed.add_field(name="Week Total", value=f"{week_posts}/7", inline=True)
    embed.add_field(name="Month Total", value=f"{month_posts}", inline=True)
    embed.add_field(name="All Time (This Server)", value=f"{info['total_posts']}", inline=True)
    embed.add_field(name="Current Streak", value=f"🔥 {info['current_streak']} days", inline=True)
    embed.add_field(name="Best Streak", value=f"🏆 {info['best_streak']} days", inline=True)
    embed.add_field(name="Last Posted", value=info.get('last_posted', 'Never'), inline=True)
    
    embed.set_footer(text="Stats are specific to this server only")
    await ctx.send(embed=embed)

@bot.command(name='help_tracker')
async def help_tracker(ctx):
    """Show all commands"""
    embed = discord.Embed(
        title="📱 Server-Specific Tracker Commands",
        description="Track posts separately per server",
        color=discord.Color.blue()
    )
    
    commands_list = [
        ("**Setup (Admin)**", ""),
        ("!setup @creator", "Setup tracking in current channel"),
        ("!unsetup", "Remove tracking from current channel"),
        ("!channels", "List tracked channels in this server"),
        ("", ""),
        ("**Reports (Server-Specific)**", ""),
        ("!dashboard", "View this server's creators"),
        ("!weekly", "Weekly report for this server"),
        ("!stats [@user]", "Individual stats in this server"),
        ("", ""),
        ("**Tracking**", ""),
        ("Type 'posted'", "Creators type this to track"),
    ]
    
    for cmd, desc in commands_list:
        if cmd:
            embed.add_field(name=cmd, value=desc or "\u200b", inline=False)
    
    embed.set_footer(text=f"Posts are tracked separately for each server!")
    
    await ctx.send(embed=embed)

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)