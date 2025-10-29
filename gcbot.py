import discord
from discord import app_commands
from discord.ext import commands
import re
import asyncio
import os
import json
from typing import Dict, Any, Tuple

# ---------------------------
# CONFIG / INTENTS
# ---------------------------

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True  # <- we need this now to read !buy
BOT_TOKEN = "BOT_TOKEN"  # rotate your old token and paste new one here

KAUFHAUS_FILE = "kaufhaus.json"
SCHWARTZ_FILE = "schwartzmarkt.json"
PLAYERS_FILE = "players.json"

HOST_PING = "<@&1427964239443656764>"  # change to your staff/host role mention for the ||@hosts|| part
HOST_ROLE_ID = 1427964239443656764  # change this to the same thing, but just the numebrs


# ---------------------------
# BASIC HELPERS
# ---------------------------

def sanitize_channel_name(name: str) -> str:
    clean = name.lower()
    clean = clean.replace(" ", "-").replace("_", "-")
    clean = re.sub(r"[^a-z0-9\-]", "", clean)
    clean = re.sub(r"-{2,}", "-", clean)
    clean = clean.strip("-")
    if len(clean) == 0:
        clean = "player"
    if len(clean) > 90:
        clean = clean[:90]
    return clean

async def channel_exists_in_category(category: discord.CategoryChannel, name: str) -> bool:
    for ch in category.channels:
        if isinstance(ch, discord.TextChannel) and ch.name == name:
            return True
    return False

async def create_private_channel(
    guild: discord.Guild,
    *,
    name: str,
    category: discord.CategoryChannel,
    player: discord.Member,
    prod_role: discord.Role | None,
    topic: str,
    intro_message: str
):
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=False
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            manage_channels=True,
            manage_messages=True
        ),
        player: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True
        )
    }

    if prod_role is not None:
        overwrites[prod_role] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True
        )

    channel = await guild.create_text_channel(
        name=name,
        category=category,
        overwrites=overwrites,
        topic=topic
    )

    await channel.send(intro_message)
    return channel


# ---------------------------
# FILE I/O HELPERS
# ---------------------------

def load_json(path: str, fallback: Dict[str, Any]) -> Dict[str, Any]:
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(fallback, f, indent=2)
        return fallback.copy()
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            # if file is corrupt, reset to fallback
            return fallback.copy()

def save_json(path: str, data: Dict[str, Any]):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def init_shop_files():
    kaufhaus_fallback = {
        "channel_id": 0,
        "items": {}
    }
    schwartz_fallback = {
        "channel_id": 0,
        "items": {}
    }
    players_fallback = {}

    kauf = load_json(KAUFHAUS_FILE, kaufhaus_fallback)
    schwar = load_json(SCHWARTZ_FILE, schwartz_fallback)
    players = load_json(PLAYERS_FILE, players_fallback)

    # Save them back to ensure files exist and are valid
    save_json(KAUFHAUS_FILE, kauf)
    save_json(SCHWARTZ_FILE, schwar)
    save_json(PLAYERS_FILE, players)

    return kauf, schwar, players


# ---------------------------
# SHOP RENDERING
# ---------------------------

def build_shop_message(shop_data: Dict[str, Any], shop_label: str | None = None) -> str:
    """
    Turn the JSON for a shop into a message string.
    shop_data: loaded JSON for this shop.
    shop_label: fallback label if shop_data doesn't include 'title'.
    """
    # title & intro customizable in the JSON
    title = shop_data.get("title") or (shop_label or "Shop")
    intro = shop_data.get("intro") or "Willkommen. Alles hat einen Preis."

    lines = []
    lines.append(f"**{title}**")
    lines.append(intro + "\n")

    for item_id, item in shop_data.get("items", {}).items():
        name = item.get("name", "???")
        desc = item.get("description", "")
        price = item.get("price", 0)
        stock = item.get("stock", "-")
        public_stock = item.get("public_stock", "n")
        role_stock = item.get("role_stock", None)

        # Decide what to show for stock
        if role_stock is not None:
            shown_stock = "?"
            if public_stock == "y":
                numeric_amounts = []
                for amt in role_stock.values():
                    if isinstance(amt, int) or (isinstance(amt, str) and amt.isdigit()):
                        numeric_amounts.append(int(amt))
                    elif isinstance(amt, str) and amt == "-":
                        numeric_amounts.append(999999)
                if numeric_amounts:
                    m = max(numeric_amounts)
                    shown_stock = "∞" if m >= 999999 else str(m)
        else:
            if stock == "-":
                shown_stock = "∞" if public_stock == "y" else "?"
            else:
                shown_stock = stock if public_stock == "y" else "?"

        lines.append(
            f"**{name}**  (`{item_id}`)\n"
            f"{desc}\n"
            f"Price: {price} DM | In Stock: {shown_stock}\n"
        )

    # footer (optional)
    lines.append("\n*Use `!buy <itemID>` to purchase.*")
    return "\n".join(lines)


async def get_last_bot_message(channel: discord.TextChannel, bot_user: discord.User):
    """
    Return (message or None) for the most recent message in channel that is either:
    - the last message in channel at all, if it's from the bot
    - else None
    """
    async for msg in channel.history(limit=1):
        if msg.author.id == bot_user.id:
            return msg
        else:
            return None
    return None


async def sync_shop_channel(bot: commands.Bot, shop_path: str):
    """
    Ensure the shop message in that channel matches the JSON.
    Creates/edits as needed.
    """
    shop_data = load_json(shop_path, {"channel_id": 0, "items": {}})
    channel_id = shop_data.get("channel_id", 0)
    if channel_id == 0:
        return  # shop not configured yet

    channel = bot.get_channel(channel_id)
    if channel is None:
        return  # channel doesn't exist / bot can't see it

    # Determine label fallback for title
    if shop_path == KAUFHAUS_FILE:
        fallback_label = "Kaufhaus"
    elif shop_path == SCHWARTZ_FILE:
        fallback_label = "Schwartzmarkt"
    else:
        fallback_label = "Shop"

    desired_text = build_shop_message(shop_data, fallback_label)

    last_bot_msg = await get_last_bot_message(channel, bot.user)
    if last_bot_msg is None:
        await channel.send(desired_text)
    else:
        if last_bot_msg.content != desired_text:
            await last_bot_msg.edit(content=desired_text)


# ---------------------------
# ECONOMY / BUY LOGIC
# ---------------------------

def find_item_in_shops(item_id: str) -> Tuple[str, Dict[str, Any]] | None:
    """
    Look for item_id in kaufhaus.json first, then schwartzmarkt.json.
    Return (which_file, item_dict) or None.
    """
    kauf = load_json(KAUFHAUS_FILE, {"channel_id": 0, "items": {}})
    if item_id in kauf.get("items", {}):
        return (KAUFHAUS_FILE, kauf["items"][item_id])

    schwar = load_json(SCHWARTZ_FILE, {"channel_id": 0, "items": {}})
    if item_id in schwar.get("items", {}):
        return (SCHWARTZ_FILE, schwar["items"][item_id])

    return None

def user_can_afford(user_id: int, cost: int) -> bool:
    players = load_players()
    pdata = players.get(str(user_id), {"money": 0, "items": [], "name": "Unknown"})
    return pdata.get("money", 0) >= cost

def deduct_money_and_give_item(user_id: int, item_id: str, price: int, member_obj: discord.Member | None):
    """
    Charge the player, add the item to their inventory, and keep their name synced.
    member_obj is the discord.Member who bought it (so we can keep name up to date).
    """
    players = load_players()
    uid = str(user_id)

    if uid not in players:
        # create new if somehow missing
        players[uid] = {
            "name": member_obj.display_name if member_obj else "Unknown",
            "money": 0,
            "items": []
        }

    pdata = players[uid]

    # sync the stored name with their current display
    if member_obj and pdata.get("name") != member_obj.display_name:
        pdata["name"] = member_obj.display_name

    # deduct
    current_money = pdata.get("money", 0)
    pdata["money"] = current_money - price
    if pdata["money"] < 0:
        pdata["money"] = 0  # safety, shouldn't really go below

    # add item
    inv = pdata.get("items", [])
    inv.append(item_id)
    pdata["items"] = inv

    players[uid] = pdata
    save_players(players)

def reduce_stock(which_file: str, item_id: str, buyer_roles: Tuple[int, ...]) -> bool:
    """
    Returns True if stock was successfully reduced (or unlimited)
    Returns False if no stock.
    We also write updated file.
    """
    shop = load_json(which_file, {"channel_id": 0, "items": {}})

    item = shop["items"][item_id]

    global_stock = item.get("stock", "-")
    role_stock = item.get("role_stock", None)

    # If there's role_stock, we try to consume from the first matching role the buyer has.
    # Priority: role_stock first (special per-tribe limit), then global.
    if role_stock:
        # find a role in buyer_roles that appears in role_stock with nonzero/available
        for r in buyer_roles:
            r_str = str(r)
            if r_str in role_stock:
                amt = role_stock[r_str]
                if amt == "-":
                    # unlimited for that role
                    # no reduction needed
                    save_json(which_file, shop)
                    return True
                elif amt.isdigit():
                    if int(amt) > 0:
                        # reduce by 1
                        new_amt = str(int(amt) - 1)
                        role_stock[r_str] = new_amt
                        item["role_stock"] = role_stock
                        shop["items"][item_id] = item
                        save_json(which_file, shop)
                        return True
                    else:
                        # this role can't buy anymore
                        return False
        # no matching role with stock
        return False

    # else use global
    if global_stock == "-":
        # unlimited
        save_json(which_file, shop)
        return True
    elif global_stock.isdigit():
        if int(global_stock) > 0:
            new_amt = str(int(global_stock) - 1)
            item["stock"] = new_amt
            shop["items"][item_id] = item
            save_json(which_file, shop)
            return True
        else:
            return False

    # fallback deny
    return False

# ---------------------------
# Creating Wallets
# ---------------------------

def load_players() -> dict:
    """Load players.json (ID -> wallet info)."""
    return load_json(PLAYERS_FILE, {})

def save_players(players: dict):
    """Write players.json back to disk."""
    save_json(PLAYERS_FILE, players)

def ensure_player_entry(user: discord.Member, players: dict) -> bool:
    """
    Make sure this user exists in players.json.
    If they don't, create them with name/money/items.
    If they DO exist, update the stored name in case it changed.
    Returns True if this was a NEW entry (not previously there),
    False if it already existed.
    """
    uid = str(user.id)
    display = user.display_name

    if uid not in players:
        players[uid] = {
            "name": display,
            "money": 0,
            "items": []
        }
        return True
    else:
        # update name if it's different
        if players[uid].get("name") != display:
            players[uid]["name"] = display
        # leave money/items alone
        return False

def get_user_wallet_dict(user_id: int) -> dict:
    """
    Return a dict with {name, money, items}.
    If the user isn't in players.json yet, we fabricate a temp zero wallet.
    We DON'T save that temp wallet here; saving/creation is handled elsewhere.
    """
    players = load_players()
    entry = players.get(str(user_id))

    if entry is None:
        # fabricate a blank preview
        return {
            "name": "Unknown",
            "money": 0,
            "items": []
        }

    return {
        "name": entry.get("name", "Unknown"),
        "money": entry.get("money", 0),
        "items": entry.get("items", [])
    }

def resolve_item_name(item_id: str) -> str:
    """
    Look up a prettier name for an itemID by checking kaufhaus.json or schwartzmarkt.json.
    Fall back to the raw ID if not found.
    """
    kauf = load_json(KAUFHAUS_FILE, {"channel_id": 0, "items": {}})
    schwar = load_json(SCHWARTZ_FILE, {"channel_id": 0, "items": {}})

    if item_id in kauf.get("items", {}):
        return kauf["items"][item_id].get("name", item_id)
    if item_id in schwar.get("items", {}):
        return schwar["items"][item_id].get("name", item_id)
    return item_id

def format_wallet_message(user: discord.Member) -> str:
    """
    Build the string we show in /wallet.
    """
    w = get_user_wallet_dict(user.id)
    money = w["money"]
    items_list = w["items"]

    if items_list:
        pretty_items = [f"{resolve_item_name(i)} (`{i}`)" for i in items_list]
        items_str = "\n".join(f"- {x}" for x in pretty_items)
    else:
        items_str = "No items."

    msg = (
        f"Wallet for **{user.display_name}** "
        f"(stored as \"{w['name']}\"):\n"
        f"Money: {money} DM\n"
        f"Items:\n{items_str}"
    )
    return msg

def is_host(member: discord.Member) -> bool:
    """
    Host permissions check.
    You can tweak this however you want (host role, admin, etc.).
    """
    if member.guild_permissions.administrator:
        return True
    for r in member.roles:
        if r.id == HOST_ROLE_ID:
            return True
    return False

# ---------------------------
# BOT SETUP
# ---------------------------

class GCBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None
        )

    async def setup_hook(self):
        # GLOBAL SYNC ONLY
        await self.tree.sync()
        print("Slash commands synced.")



bot = GCBot()


# ---------------------------
# SLASH COMMAND: /confsetup
# ---------------------------

@bot.tree.command(
    name="confsetup",
    description="Create conf/submission channels for each member of a role."
)
@app_commands.describe(
    role="Players role.",
    conf_category="Category for confessionals.",
    submissions_category="Category for submissions (optional).",
    prod_role="Staff role with access (optional)."
)
async def confsetup(
    interaction: discord.Interaction,
    role: discord.Role,
    conf_category: discord.CategoryChannel,
    submissions_category: discord.CategoryChannel | None = None,
    prod_role: discord.Role | None = None
):
    guild = interaction.guild
    if guild is None:
        await interaction.response.send_message(
            "Use this in a server.",
            ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True, thinking=True)

    players_role_members = role.members

    created_conf_channels = []
    created_sub_channels = []
    skipped_conf_existing = []
    skipped_sub_existing = []

    for member in players_role_members:
        base_name = sanitize_channel_name(member.display_name)

        # Conf channel
        conf_name = base_name
        already_conf = await channel_exists_in_category(conf_category, conf_name)

        if already_conf:
            skipped_conf_existing.append((member, conf_name))
        else:
            topic = f"Confessional for {member.display_name}"
            intro_msg = (
                f"Willkommen to your confessional, {member.mention}. "
                "Report your thoughts here. Alles wird überwacht. 🕵️"
            )
            ch = await create_private_channel(
                guild,
                name=conf_name,
                category=conf_category,
                player=member,
                prod_role=prod_role,
                topic=topic,
                intro_message=intro_msg
            )
            created_conf_channels.append((member, ch))

        # Submissions channel
        if submissions_category is not None:
            sub_name = f"{base_name}-submissions"
            already_sub = await channel_exists_in_category(submissions_category, sub_name)

            if already_sub:
                skipped_sub_existing.append((member, sub_name))
            else:
                topic_sub = f"Challenge submissions for {member.display_name}"
                intro_sub = (
                    f"{member.mention} — post your official answers here. "
                    "Edits after deadline will not count."
                )
                subch = await create_private_channel(
                    guild,
                    name=sub_name,
                    category=submissions_category,
                    player=member,
                    prod_role=prod_role,
                    topic=topic_sub,
                    intro_message=intro_sub
                )
                created_sub_channels.append((member, subch))

        await asyncio.sleep(0.3)

    summary_lines = []
    summary_lines.append(f"Done in **{guild.name}**.")
    summary_lines.append(f"Players with {role.mention}: {len(players_role_members)}")

    if created_conf_channels:
        summary_lines.append(
            f"Created {len(created_conf_channels)} confessional channel(s) in {conf_category.name}."
        )
    if skipped_conf_existing:
        summary_lines.append(
            f"Skipped {len(skipped_conf_existing)} confessional channel(s) (already existed)."
        )

    if submissions_category is not None:
        if created_sub_channels:
            summary_lines.append(
                f"Created {len(created_sub_channels)} submissions channel(s) in {submissions_category.name}."
            )
        if skipped_sub_existing:
            summary_lines.append(
                f"Skipped {len(skipped_sub_existing)} submissions channel(s) (already existed)."
            )

    await interaction.followup.send(
        "\n".join(summary_lines),
        ephemeral=True
    )
@bot.tree.command(
    name="wallet",
    description="Check a wallet. Hosts can view anyone; players can view themselves."
)
@app_commands.describe(
    player="Whose wallet to view. Leave empty to view your own."
)
async def wallet_cmd(
    interaction: discord.Interaction,
    player: discord.Member | None = None
):
    guild = interaction.guild
    if guild is None:
        await interaction.response.send_message(
            "Use this in a server.",
            ephemeral=True
        )
        return

    requester: discord.Member = interaction.user

    # Who are we allowed to inspect?
    if is_host(requester):
        target = player or requester
    else:
        if player is None or player.id == requester.id:
            target = requester
        else:
            await interaction.response.send_message(
                "You can only view your own wallet.",
                ephemeral=True
            )
            return

    msg = format_wallet_message(target)

    await interaction.response.send_message(
        msg,
        ephemeral=True
    )
@bot.tree.command(
    name="walletcreate",
    description="Add players to the economy file with empty wallets (hosts only)."
)
@app_commands.describe(
    user="Create/update wallet for this user.",
    role="Or create/update wallets for everyone with this role."
)
async def walletcreate_cmd(
    interaction: discord.Interaction,
    user: discord.Member | None = None,
    role: discord.Role | None = None
):
    guild = interaction.guild
    if guild is None:
        await interaction.response.send_message(
            "Use this in a server.",
            ephemeral=True
        )
        return

    requester: discord.Member = interaction.user

    # Only hosts:
    if not is_host(requester):
        await interaction.response.send_message(
            "You do not have permission to do that.",
            ephemeral=True
        )
        return

    players = load_players()

    new_count = 0
    touched_members: list[discord.Member] = []

    # Single user
    if user is not None:
        if ensure_player_entry(user, players):
            new_count += 1
        touched_members.append(user)

    # Role batch
    if role is not None:
        for m in role.members:
            if ensure_player_entry(m, players):
                new_count += 1
            touched_members.append(m)

    save_players(players)

    if not touched_members:
        summary = "No targets provided. Specify a user or a role."
    else:
        uniq_ids = {m.id for m in touched_members}
        summary = (
            f"Registered {len(uniq_ids)} player(s). "
            f"New wallets created: {new_count}."
        )

    await interaction.response.send_message(
        summary,
        ephemeral=True
    ) 

# ---------------------------
# TEXT COMMAND: !buy
# ---------------------------

@bot.command(name="buy")
async def buy_command(ctx: commands.Context, item_id: str):
    """
    !buy <itemID>
    - checks price, stock, money
    - deducts money
    - grants item
    - announces purchase
    - refreshes shop messages
    """
    buyer = ctx.author
    buyer_id = buyer.id
    buyer_roles = tuple([r.id for r in buyer.roles if not r.is_default()])

    # find item in either shop
    res = find_item_in_shops(item_id)
    if res is None:
        await ctx.send(f"{buyer.mention} That item doesn't exist.")
        return

    which_file, item_data = res
    price = int(item_data.get("price", 0))

    # check stock availability without mutating yet
    # we'll simulate reduce_stock() logic lightly:
    # 1) if role_stock exists, see if any buyer role has >0 or "-"
    # 2) else check global
    role_stock = item_data.get("role_stock", None)
    global_stock = item_data.get("stock", "-")

    def has_role_stock():
        if not role_stock:
            return False
        for r in buyer_roles:
            r_str = str(r)
            if r_str in role_stock:
                amt = role_stock[r_str]
                if amt == "-":
                    return True
                if amt.isdigit() and int(amt) > 0:
                    return True
        return False

    def has_global_stock():
        if role_stock:
            return False  # priority to role_stock, treat as gated
        if global_stock == "-":
            return True
        if global_stock.isdigit() and int(global_stock) > 0:
            return True
        return False

    stock_ok = has_role_stock() or has_global_stock()
    if not stock_ok:
        await ctx.send(f"{buyer.mention} That item is sold out for you.")
        return

    # check money
    if not user_can_afford(buyer_id, price):
        await ctx.send(f"{buyer.mention} You don't have enough Deutsche Marks.")
        return

    # actually deduct 1 stock and charge
    took_stock = reduce_stock(which_file, item_id, buyer_roles)
    if not took_stock:
        await ctx.send(f"{buyer.mention} Someone just grabbed the last one. Too slow.")
        return

    # now take money and add item to inventory
    deduct_money_and_give_item(buyer_id, item_id, price, ctx.author)

    # Announce
    item_name = item_data.get("name", item_id)
    await ctx.send(
        f"Congratulations, {buyer.mention}! You just bought **{item_name}**. ||{HOST_PING}||"
    )

    # re-sync shop messages so stock display updates
    await sync_shop_channel(bot, KAUFHAUS_FILE)
    await sync_shop_channel(bot, SCHWARTZ_FILE)


# ---------------------------
# EVENTS
# ---------------------------

@bot.event
async def on_ready():
    # init files
    init_shop_files()

    # set status
    await bot.change_presence(
        activity=discord.CustomActivity(name="Coming up with challenges")
    )

    # sync both shop channels to reflect latest JSON on startup
    await sync_shop_channel(bot, KAUFHAUS_FILE)
    await sync_shop_channel(bot, SCHWARTZ_FILE)

    print(f"GCbot is online as {bot.user} (id={bot.user.id})")
@bot.event
async def on_ready():
    # init files
    init_shop_files()

    # set status
    await bot.change_presence(
        activity=discord.CustomActivity(name="Coming up with challenges")
    )

    # sync shop channels
    await sync_shop_channel(bot, KAUFHAUS_FILE)
    await sync_shop_channel(bot, SCHWARTZ_FILE)

    print(f"GCbot is online as {bot.user} (id={bot.user.id})")

# ---------------------------
# RUN
# ---------------------------

if __name__ == "__main__":
    if BOT_TOKEN == "PUT_YOUR_TOKEN_HERE":
        raise RuntimeError("You forgot to set BOT_TOKEN in the script.")
    bot.run(BOT_TOKEN)
