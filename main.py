import os
import json
import sqlite3
import time
from threading import Thread
from flask import Flask
import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import Button, View, Select, Modal, TextInput

# =========================
# Flaskでのkeep_alive
# =========================
app = Flask("")

@app.route("/")
def home():
    return "I'm alive"

def run():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

def keep_alive():
    t = Thread(target=run)
    t.start()

# =========================
# 設定
# =========================
DATA_FILE = "products.json"
SHOP_MSG_FILE = "shop_messages.json"
ADMIN_CHANNEL_ID = 1292094034441142302
RESULT_CHANNEL_ID = 1200371155123589201
GUILD_ID = 1200368636922167339
GUILD = discord.Object(id=GUILD_ID)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# =========================
# SQLiteによる永続保存
# =========================
conn = sqlite3.connect("shop.db")
c = conn.cursor()
c.execute("""CREATE TABLE IF NOT EXISTS products (
    name TEXT PRIMARY KEY,
    price INTEGER
)""")
c.execute("""CREATE TABLE IF NOT EXISTS stock (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_name TEXT,
    item TEXT
)""")
conn.commit()

# JSONでショップメッセージ保存
def load_shop_messages():
    if os.path.exists(SHOP_MSG_FILE):
        with open(SHOP_MSG_FILE, "r") as f:
            return json.load(f)
    return []

def save_shop_messages():
    with open(SHOP_MSG_FILE, "w") as f:
        json.dump(shop_messages, f)

shop_messages = load_shop_messages()

# =========================
# 商品操作関数
# =========================
def get_products():
    c.execute("SELECT name, price FROM products")
    items = {}
    for name, price in c.fetchall():
        c.execute("SELECT item FROM stock WHERE product_name = ?", (name,))
        stock_list = [i[0] for i in c.fetchall()]
        items[name] = {"price": price, "stock_list": stock_list}
    return items

def save_product(name, price):
    c.execute("INSERT OR REPLACE INTO products(name, price) VALUES (?,?)", (name, price))
    conn.commit()

def delete_product(name):
    c.execute("DELETE FROM products WHERE name=?", (name,))
    c.execute("DELETE FROM stock WHERE product_name=?", (name,))
    conn.commit()

def add_stock(name, items):
    for item in items:
        c.execute("INSERT INTO stock(product_name, item) VALUES (?,?)", (name, item))
    conn.commit()

def remove_stock(name, qty):
    c.execute("SELECT id FROM stock WHERE product_name=? ORDER BY id ASC LIMIT ?", (name, qty))
    ids = [i[0] for i in c.fetchall()]
    for _id in ids:
        c.execute("DELETE FROM stock WHERE id=?", (_id,))
    conn.commit()
    return ids

PRODUCTS = get_products()

# =========================
# ショップEmbed生成
# =========================
def generate_shop_embed():
    embed = discord.Embed(title="🛒 ショップ", color=0x00FF88)
    if not PRODUCTS:
        embed.description = "商品がありません"
    for n, i in PRODUCTS.items():
        embed.add_field(
            name=n,
            value=f"価格:{i['price']}円 在庫:{len(i['stock_list'])}",
            inline=False
        )
    return embed

async def update_all_shop_messages():
    for data in shop_messages:
        try:
            channel = bot.get_channel(data["channel_id"])
            msg = await channel.fetch_message(data["message_id"])
            await msg.edit(embed=generate_shop_embed(), view=ShopView())
        except:
            pass

# =========================
# 購入モーダル
# =========================
class PurchaseModal(Modal):
    def __init__(self, product):
        super().__init__(title=f"{product} 購入")
        self.product = product
        self.qty = TextInput(label="数量")
        self.pay = TextInput(label="PayPayリンク")
        self.add_item(self.qty)
        self.add_item(self.pay)

    async def on_submit(self, interaction: discord.Interaction):
        pay_text = self.pay.value.lower()
        if not ("https://" in pay_text and "paypay" in pay_text and "ne" in pay_text and "jp" in pay_text):
            await interaction.response.send_message(
                "❌ 正しいPayPayリンクではありません。正しいリンクを入力してください。",
                ephemeral=True
            )
            return

        try:
            qty = int(self.qty.value)
            if qty <= 0:
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "❌ 数量は1以上の数字で入力してください。",
                ephemeral=True
            )
            return

        admin = bot.get_channel(ADMIN_CHANNEL_ID)
        if admin is None:
            await interaction.response.send_message(
                "❌ 管理者チャンネルが見つかりません。",
                ephemeral=True
            )
            return

        items_stock = PRODUCTS[self.product]["stock_list"]
        if qty > len(items_stock):
            await interaction.response.send_message("❌ 在庫不足です", ephemeral=True)
            return

        embed = discord.Embed(title="購入申請")
        embed.add_field(name="購入者", value=interaction.user.mention)
        embed.add_field(name="商品", value=self.product)
        embed.add_field(name="数量", value=str(qty))
        embed.add_field(name="PayPay", value=self.pay.value)

        await admin.send(embed=embed, view=AdminConfirmView(interaction.user.id, self.product, qty, self.pay.value))
        await interaction.response.send_message("✅ 申請完了", ephemeral=True)

# =========================
# セレクト・ビュー
# =========================
class ProductSelect(Select):
    def __init__(self):
        super().__init__(placeholder="商品選択", options=[discord.SelectOption(label=n) for n in PRODUCTS])

    async def callback(self, interaction: discord.Interaction):
        if not PRODUCTS[self.values[0]]["stock_list"]:
            await interaction.response.send_message("在庫なし", ephemeral=True)
            return
        await interaction.response.send_modal(PurchaseModal(self.values[0]))

class ShopView(View):
    def __init__(self):
        super().__init__(timeout=None)
        if PRODUCTS:
            self.add_item(ProductSelect())

# =========================
# 管理者ビュー
# =========================
class AdminConfirmView(View):
    def __init__(self, user_id, product, qty, pay_url):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.product = product
        self.qty = qty
        self.pay_url = pay_url

    @discord.ui.button(label="送信", style=discord.ButtonStyle.green)
    async def send(self, interaction: discord.Interaction, button: Button):
        user = await bot.fetch_user(self.user_id)
        stock_items = PRODUCTS[self.product]["stock_list"][:self.qty]
        remove_stock(self.product, self.qty)
        PRODUCTS[self.product]["stock_list"] = PRODUCTS[self.product]["stock_list"][self.qty:]
        await update_all_shop_messages()
        await user.send(f"✅ 入金確認できました！\n商品：{self.product}\n内容:\n" + "\n".join(stock_items))
        result_channel = bot.get_channel(RESULT_CHANNEL_ID)
        await result_channel.send(f"📝 {user.mention} が {self.product} を {self.qty}個購入")
        await interaction.response.send_message("送信完了", ephemeral=True)

    @discord.ui.button(label="金額が違う（キャンセル）", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: Button):
        user = await bot.fetch_user(self.user_id)
        await user.send("❌ 支払い金額が確認できませんでした。再度送金してください。")
        await interaction.response.send_message("取引キャンセル", ephemeral=True)

# =========================
# Slashコマンド
# =========================
@bot.tree.command(name="shop")
@app_commands.guilds(GUILD)
async def shop(interaction: discord.Interaction):
    await interaction.response.send_message(embed=generate_shop_embed(), view=ShopView())
    msg = await interaction.original_response()
    shop_messages.append({"channel_id": msg.channel.id, "message_id": msg.id})
    save_shop_messages()

@bot.tree.command(name="add_product")
@app_commands.guilds(GUILD)
async def add_product(interaction: discord.Interaction, name: str, price: int):
    save_product(name, price)
    PRODUCTS[name] = {"price": price, "stock_list": []}
    await update_all_shop_messages()
    await interaction.response.send_message("追加完了")

@bot.tree.command(name="delete_product")
@app_commands.guilds(GUILD)
async def delete_product(interaction: discord.Interaction):
    class Sel(Select):
        def __init__(self):
            super().__init__(placeholder="削除する商品", options=[discord.SelectOption(label=n) for n in PRODUCTS])

        async def callback(self, interaction2: discord.Interaction):
            product = self.values[0]
            delete_product(product)
            PRODUCTS.pop(product)
            await update_all_shop_messages()
            await interaction2.response.send_message(f"{product} を削除しました", ephemeral=True)

    view = View(timeout=None)
    view.add_item(Sel())
    await interaction.response.send_message("削除する商品を選択", view=view, ephemeral=True)

# =========================
# 起動
# =========================
@bot.event
async def on_ready():
    await bot.tree.sync(guild=GUILD)
    bot.add_view(ShopView())
    print("BOT起動")

# =========================
# 永続起動ループ
# =========================
while True:
    try:
        print("Starting bot...")
        keep_alive()
        bot.run(os.getenv("TOKEN"))
    except Exception as e:
        print("Bot crashed:", e)
        print("Restarting in 10秒...")
        time.sleep(10)
