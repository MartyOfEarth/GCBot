diff --git a/gcbot.py b/gcbot.py
index ecfd79fa61a60b60d3692f37c53bff97c65105a0..80e85fb6f11b2fe41c79b1f4b7d9af77e9fac425 100644
--- a/gcbot.py
+++ b/gcbot.py
@@ -1,33 +1,33 @@
 import discord
 from discord import app_commands
 from discord.ext import commands
 import re
 import asyncio
 import os
 import json
-from typing import Dict, Any, Tuple
+from typing import Dict, Any, Tuple, Literal
 
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
@@ -409,71 +409,119 @@ def get_user_wallet_dict(user_id: int) -> dict:
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
 
-def format_wallet_message(user: discord.Member) -> str:
-    """
-    Build the string we show in /wallet.
-    """
-    w = get_user_wallet_dict(user.id)
-    money = w["money"]
-    items_list = w["items"]
-
-    if items_list:
-        pretty_items = [f"{resolve_item_name(i)} (`{i}`)" for i in items_list]
-        items_str = "\n".join(f"- {x}" for x in pretty_items)
-    else:
-        items_str = "No items."
-
-    msg = (
-        f"Wallet for **{user.display_name}** "
-        f"(stored as \"{w['name']}\"):\n"
-        f"Money: {money} DM\n"
-        f"Items:\n{items_str}"
-    )
-    return msg
+def format_wallet_message(user: discord.Member) -> str:
+    """
+    Build the string we show when displaying a wallet.
+    """
+    w = get_user_wallet_dict(user.id)
+    money = w["money"]
+    items_list = w["items"]
+
+    if items_list:
+        pretty_items = [f"{resolve_item_name(i)} (`{i}`)" for i in items_list]
+        items_str = "\n".join(f"- {x}" for x in pretty_items)
+    else:
+        items_str = "No items."
+
+    msg = (
+        f"Wallet for **{user.display_name}** "
+        f"(stored as \"{w['name']}\"):\n"
+        f"Money: {money} DM\n"
+        f"Items:\n{items_str}"
+    )
+    return msg
+
+
+def reset_wallet_entry(entry: dict):
+    """Reset the given wallet entry in-place to zero money and no items."""
+    entry["money"] = 0
+    entry["items"] = []
+
+
+def apply_to_targets(
+    *,
+    user: discord.Member | None,
+    role: discord.Role | None,
+    action
+):
+    """
+    Helper to gather targets (user and/or members of role) and run an action.
+    The action should be a callable taking a discord.Member and returning bool
+    indicating whether it made a change.
+    Returns (touched_members_list, success_count).
+    """
+    touched: list[discord.Member] = []
+    seen_ids: set[int] = set()
+    success_count = 0
+
+    if user is not None:
+        touched.append(user)
+        seen_ids.add(user.id)
+
+    if role is not None:
+        for member in role.members:
+            if member.id not in seen_ids:
+                touched.append(member)
+                seen_ids.add(member.id)
+
+    for member in touched:
+        if action(member):
+            success_count += 1
+
+    return touched, success_count
+
+
+def get_shop_file_and_label(shop_key: str) -> tuple[str, str]:
+    shop_key = shop_key.lower()
+    if shop_key == "kaufhaus":
+        return KAUFHAUS_FILE, "Kaufhaus"
+    if shop_key == "schwartzmarkt":
+        return SCHWARTZ_FILE, "Schwartzmarkt"
+    raise ValueError("Unknown shop key")
 
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
 
@@ -582,161 +630,401 @@ async def confsetup(
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
-@bot.tree.command(
-    name="wallet",
-    description="Check a wallet. Hosts can view anyone; players can view themselves."
-)
-@app_commands.describe(
-    player="Whose wallet to view. Leave empty to view your own."
-)
-async def wallet_cmd(
-    interaction: discord.Interaction,
-    player: discord.Member | None = None
-):
-    guild = interaction.guild
-    if guild is None:
-        await interaction.response.send_message(
-            "Use this in a server.",
-            ephemeral=True
-        )
-        return
-
-    requester: discord.Member = interaction.user
-
-    # Who are we allowed to inspect?
-    if is_host(requester):
-        target = player or requester
-    else:
-        if player is None or player.id == requester.id:
-            target = requester
-        else:
-            await interaction.response.send_message(
-                "You can only view your own wallet.",
-                ephemeral=True
-            )
-            return
-
-    msg = format_wallet_message(target)
-
-    await interaction.response.send_message(
-        msg,
-        ephemeral=True
-    )
-@bot.tree.command(
-    name="walletcreate",
-    description="Add players to the economy file with empty wallets (hosts only)."
-)
-@app_commands.describe(
-    user="Create/update wallet for this user.",
-    role="Or create/update wallets for everyone with this role."
-)
-async def walletcreate_cmd(
-    interaction: discord.Interaction,
-    user: discord.Member | None = None,
-    role: discord.Role | None = None
-):
-    guild = interaction.guild
-    if guild is None:
-        await interaction.response.send_message(
-            "Use this in a server.",
-            ephemeral=True
-        )
-        return
-
-    requester: discord.Member = interaction.user
-
-    # Only hosts:
-    if not is_host(requester):
-        await interaction.response.send_message(
-            "You do not have permission to do that.",
-            ephemeral=True
-        )
-        return
-
-    players = load_players()
-
-    new_count = 0
-    touched_members: list[discord.Member] = []
-
-    # Single user
-    if user is not None:
-        if ensure_player_entry(user, players):
-            new_count += 1
-        touched_members.append(user)
-
-    # Role batch
-    if role is not None:
-        for m in role.members:
-            if ensure_player_entry(m, players):
-                new_count += 1
-            touched_members.append(m)
-
-    save_players(players)
-
-    if not touched_members:
-        summary = "No targets provided. Specify a user or a role."
-    else:
-        uniq_ids = {m.id for m in touched_members}
-        summary = (
-            f"Registered {len(uniq_ids)} player(s). "
-            f"New wallets created: {new_count}."
-        )
-
-    await interaction.response.send_message(
-        summary,
-        ephemeral=True
-    ) 
-
-# ---------------------------
-# TEXT COMMAND: !buy
-# ---------------------------
-
-@bot.command(name="buy")
-async def buy_command(ctx: commands.Context, item_id: str):
+wallet_group = app_commands.Group(
+    name="wallet",
+    description="Host tools for managing player wallets."
+)
+
+
+@wallet_group.command(name="view", description="View any player's wallet.")
+@app_commands.describe(
+    player="Whose wallet to view. Leave empty to view yourself."
+)
+async def wallet_view_cmd(
+    interaction: discord.Interaction,
+    player: discord.Member | None = None
+):
+    guild = interaction.guild
+    if guild is None:
+        await interaction.response.send_message(
+            "Use this in a server.",
+            ephemeral=True
+        )
+        return
+
+    requester = interaction.user
+    if not isinstance(requester, discord.Member) or not is_host(requester):
+        await interaction.response.send_message(
+            "You do not have permission to do that.",
+            ephemeral=True
+        )
+        return
+
+    target = player or requester
+    msg = format_wallet_message(target)
+
+    await interaction.response.send_message(
+        msg,
+        ephemeral=True
+    )
+
+
+@wallet_group.command(name="create", description="Create wallets for players or a role.")
+@app_commands.describe(
+    user="Create or update a wallet for this user.",
+    role="Or create/update wallets for everyone with this role."
+)
+async def wallet_create_cmd(
+    interaction: discord.Interaction,
+    user: discord.Member | None = None,
+    role: discord.Role | None = None
+):
+    guild = interaction.guild
+    if guild is None:
+        await interaction.response.send_message(
+            "Use this in a server.",
+            ephemeral=True
+        )
+        return
+
+    requester = interaction.user
+    if not isinstance(requester, discord.Member) or not is_host(requester):
+        await interaction.response.send_message(
+            "You do not have permission to do that.",
+            ephemeral=True
+        )
+        return
+
+    players = load_players()
+
+    def action(member: discord.Member) -> bool:
+        return ensure_player_entry(member, players)
+
+    touched, created = apply_to_targets(user=user, role=role, action=action)
+    save_players(players)
+
+    if not touched:
+        summary = "Provide a user or a role to target."
+    else:
+        summary = (
+            f"Touched {len(touched)} player(s). "
+            f"New wallets created: {created}."
+        )
+
+    await interaction.response.send_message(summary, ephemeral=True)
+
+
+@wallet_group.command(name="delete", description="Delete wallets for a user or role.")
+@app_commands.describe(
+    user="Delete this user's wallet.",
+    role="Or delete wallets for everyone with this role."
+)
+async def wallet_delete_cmd(
+    interaction: discord.Interaction,
+    user: discord.Member | None = None,
+    role: discord.Role | None = None
+):
+    guild = interaction.guild
+    if guild is None:
+        await interaction.response.send_message(
+            "Use this in a server.",
+            ephemeral=True
+        )
+        return
+
+    requester = interaction.user
+    if not isinstance(requester, discord.Member) or not is_host(requester):
+        await interaction.response.send_message(
+            "You do not have permission to do that.",
+            ephemeral=True
+        )
+        return
+
+    players = load_players()
+
+    def action(member: discord.Member) -> bool:
+        uid = str(member.id)
+        if uid in players:
+            del players[uid]
+            return True
+        return False
+
+    touched, deleted = apply_to_targets(user=user, role=role, action=action)
+    save_players(players)
+
+    if not touched:
+        summary = "Provide a user or a role to target."
+    else:
+        summary = (
+            f"Touched {len(touched)} player(s). "
+            f"Wallets deleted: {deleted}."
+        )
+
+    await interaction.response.send_message(summary, ephemeral=True)
+
+
+@wallet_group.command(name="reset", description="Reset wallets to zero for a user or role.")
+@app_commands.describe(
+    user="Reset this user's wallet.",
+    role="Or reset wallets for everyone with this role."
+)
+async def wallet_reset_cmd(
+    interaction: discord.Interaction,
+    user: discord.Member | None = None,
+    role: discord.Role | None = None
+):
+    guild = interaction.guild
+    if guild is None:
+        await interaction.response.send_message(
+            "Use this in a server.",
+            ephemeral=True
+        )
+        return
+
+    requester = interaction.user
+    if not isinstance(requester, discord.Member) or not is_host(requester):
+        await interaction.response.send_message(
+            "You do not have permission to do that.",
+            ephemeral=True
+        )
+        return
+
+    players = load_players()
+
+    def action(member: discord.Member) -> bool:
+        uid = str(member.id)
+        if uid not in players:
+            players[uid] = {
+                "name": member.display_name,
+                "money": 0,
+                "items": []
+            }
+            return True
+
+        entry = players[uid]
+        if entry.get("name") != member.display_name:
+            entry["name"] = member.display_name
+        reset_wallet_entry(entry)
+        players[uid] = entry
+        return True
+
+    touched, resets = apply_to_targets(user=user, role=role, action=action)
+    save_players(players)
+
+    if not touched:
+        summary = "Provide a user or a role to target."
+    else:
+        summary = (
+            f"Touched {len(touched)} player(s). "
+            f"Wallets reset: {resets}."
+        )
+
+    await interaction.response.send_message(summary, ephemeral=True)
+
+
+bot.tree.add_command(wallet_group)
+
+
+store_group = app_commands.Group(
+    name="store",
+    description="Host tools for editing shop inventory."
+)
+
+
+@store_group.command(name="add", description="Add or update an item in a store.")
+@app_commands.describe(
+    shop="Which store to edit (kaufhaus or schwartzmarkt).",
+    item_id="Unique ID for the item.",
+    name="Display name shown to players.",
+    price="Cost in Deutsche Marks.",
+    description="Description for the item.",
+    stock="How many are available (-1 for unlimited).",
+    public_stock="Should players see the remaining stock?"
+)
+async def store_add_cmd(
+    interaction: discord.Interaction,
+    shop: Literal["kaufhaus", "schwartzmarkt"],
+    item_id: str,
+    name: str,
+    price: int,
+    description: str,
+    stock: int,
+    public_stock: bool
+):
+    guild = interaction.guild
+    if guild is None:
+        await interaction.response.send_message(
+            "Use this in a server.",
+            ephemeral=True
+        )
+        return
+
+    requester = interaction.user
+    if not isinstance(requester, discord.Member) or not is_host(requester):
+        await interaction.response.send_message(
+            "You do not have permission to do that.",
+            ephemeral=True
+        )
+        return
+
+    try:
+        shop_file, shop_label = get_shop_file_and_label(shop)
+    except ValueError:
+        await interaction.response.send_message(
+            "Unknown shop.",
+            ephemeral=True
+        )
+        return
+
+    shop_data = load_json(shop_file, {"channel_id": 0, "items": {}})
+    items = shop_data.setdefault("items", {})
+    previous_entry = items.get(item_id, {})
+
+    stored_stock = "-" if stock < 0 else str(stock)
+    items[item_id] = {
+        "name": name,
+        "description": description,
+        "price": price,
+        "stock": stored_stock,
+        "public_stock": "y" if public_stock else "n",
+        "role_stock": previous_entry.get("role_stock")
+    }
+
+    save_json(shop_file, shop_data)
+    await sync_shop_channel(bot, shop_file)
+
+    status = "updated" if previous_entry else "added"
+    stock_text = "unlimited" if stored_stock == "-" else stored_stock
+    visibility = "visible" if public_stock else "hidden"
+
+    await interaction.response.send_message(
+        (
+            f"Item `{item_id}` {status} in {shop_label}. "
+            f"Price: {price} DM, Stock: {stock_text} ({visibility})."
+        ),
+        ephemeral=True
+    )
+
+
+@store_group.command(name="remove", description="Remove an item from a store.")
+@app_commands.describe(
+    shop="Which store to edit (kaufhaus or schwartzmarkt).",
+    item_id="ID of the item to remove."
+)
+async def store_remove_cmd(
+    interaction: discord.Interaction,
+    shop: Literal["kaufhaus", "schwartzmarkt"],
+    item_id: str
+):
+    guild = interaction.guild
+    if guild is None:
+        await interaction.response.send_message(
+            "Use this in a server.",
+            ephemeral=True
+        )
+        return
+
+    requester = interaction.user
+    if not isinstance(requester, discord.Member) or not is_host(requester):
+        await interaction.response.send_message(
+            "You do not have permission to do that.",
+            ephemeral=True
+        )
+        return
+
+    try:
+        shop_file, shop_label = get_shop_file_and_label(shop)
+    except ValueError:
+        await interaction.response.send_message(
+            "Unknown shop.",
+            ephemeral=True
+        )
+        return
+
+    shop_data = load_json(shop_file, {"channel_id": 0, "items": {}})
+    items = shop_data.get("items", {})
+
+    if item_id not in items:
+        await interaction.response.send_message(
+            f"Item `{item_id}` was not found in {shop_label}.",
+            ephemeral=True
+        )
+        return
+
+    del items[item_id]
+    shop_data["items"] = items
+    save_json(shop_file, shop_data)
+    await sync_shop_channel(bot, shop_file)
+
+    await interaction.response.send_message(
+        f"Item `{item_id}` removed from {shop_label}.",
+        ephemeral=True
+    )
+
+
+bot.tree.add_command(store_group)
+
+# ---------------------------
+# TEXT COMMAND: !buy
+# ---------------------------
+
+@bot.command(name="wallet")
+async def wallet_text_command(ctx: commands.Context):
+    """Show the calling player's wallet."""
+    players = load_players()
+    ensure_player_entry(ctx.author, players)
+    save_players(players)
+
+    msg = format_wallet_message(ctx.author)
+    await ctx.send(msg)
+
+
+@bot.command(name="buy")
+async def buy_command(ctx: commands.Context, item_id: str):
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
