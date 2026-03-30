import os, json, time
        import asyncio
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
            Thread(target=run).start()

        # =========================
        # ファイル設定
        # =========================
        DATA_FILE = "products.json"
        SHOP_MSG_FILE = "shop_messages.json"
        INFO_FILE = "info.json"

        ADMIN_CHANNEL_ID = 1292094034441142302
        RESULT_CHANNEL_ID = 1200371155123589201
        GUILD_ID = 1200368636922167339
        GUILD = discord.Object(id=GUILD_ID)

        intents = discord.Intents.default()
        intents.message_content = True
        bot = commands.Bot(command_prefix="!", intents=intents)

        # =========================
        # データ読み込み
        # =========================
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                PRODUCTS = json.load(f)
        else:
            PRODUCTS = {}

        if os.path.exists(SHOP_MSG_FILE):
            with open(SHOP_MSG_FILE, "r", encoding="utf-8") as f:
                shop_messages = json.load(f)
        else:
            shop_messages = []

        if os.path.exists(INFO_FILE):
            with open(INFO_FILE, "r", encoding="utf-8") as f:
                info = json.load(f)
        else:
            info = {}  # 任意の永続情報

        # =========================
        # 保存関数
        # =========================
        def save_products():
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(PRODUCTS, f, ensure_ascii=False, indent=4)

        def save_shop_messages():
            with open(SHOP_MSG_FILE, "w", encoding="utf-8") as f:
                json.dump(shop_messages, f, ensure_ascii=False, indent=4)

        def save_info():
            with open(INFO_FILE, "w", encoding="utf-8") as f:
                json.dump(info, f, ensure_ascii=False, indent=4)

        # =========================
        # SHOP Embed
        # =========================
        def generate_shop_embed():
            embed = discord.Embed(title="🛒 ショップ", color=0x00FF88)
            if not PRODUCTS:
                embed.description = "商品がありません"
            for n, i in PRODUCTS.items():
                embed.add_field(
                    name=n,
                    value=f"価格:{i['price']}円 在庫:{len(i['stock_list'])}",
                    inline=False,
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
        # モーダル・ビュー（省略せず全部保持）
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
                # PayPayリンク確認
                pay_text = self.pay.value.lower()
                if not ("https://" in pay_text and "paypay" in pay_text and "ne" in pay_text and "jp" in pay_text):
                    await interaction.response.send_message("❌ 正しいPayPayリンクではありません。", ephemeral=True)
                    return
                try:
                    qty = int(self.qty.value)
                    if qty <= 0:
                        raise ValueError
                except ValueError:
                    await interaction.response.send_message("❌ 数量は1以上の数字で入力してください。", ephemeral=True)
                    return

                admin = bot.get_channel(ADMIN_CHANNEL_ID)
                if admin is None:
                    await interaction.response.send_message("❌ 管理者チャンネルが見つかりません。", ephemeral=True)
                    return

                stock_list = PRODUCTS[self.product]["stock_list"]
                if qty > len(stock_list):
                    await interaction.response.send_message("❌ 在庫不足です", ephemeral=True)
                    return

                # 購入申請を管理者チャンネルに送信
                embed = discord.Embed(title="購入申請")
                embed.add_field(name="購入者", value=interaction.user.mention)
                embed.add_field(name="商品", value=self.product)
                embed.add_field(name="数量", value=str(qty))
                embed.add_field(name="PayPay", value=self.pay.value)

                await admin.send(embed=embed, view=AdminConfirmView(interaction.user.id, self.product, qty, self.pay.value))
                await interaction.response.send_message("✅ 申請完了", ephemeral=True)

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
        # 管理者確認ビュー
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
                stock = PRODUCTS[self.product]["stock_list"]
                if self.qty > len(stock):
                    await interaction.response.send_message("在庫不足", ephemeral=True)
                    return
                items = [stock.pop(0) for _ in range(self.qty)]
                save_products()
                await update_all_shop_messages()

                user = await bot.fetch_user(self.user_id)
                await user.send(f"✅ 入金確認できました！\n商品：{self.product}\n内容:\n" + "\n".join(items))

                result = bot.get_channel(RESULT_CHANNEL_ID)
                await result.send(f"📝 {user.mention} が {self.product} を {self.qty}個購入")

                await interaction.response.send_message("送信完了", ephemeral=True)

            @discord.ui.button(label="金額が違う（キャンセル）", style=discord.ButtonStyle.red)
            async def cancel(self, interaction: discord.Interaction, button: Button):
                user = await bot.fetch_user(self.user_id)
                await user.send("❌ 支払い金額が確認できませんでした。再度送金してください。")
                await interaction.response.send_message("取引キャンセル", ephemeral=True)

        # =========================
        # 管理UI
        # =========================
        class AdminProductSelect(Select):
            def __init__(self):
                super().__init__(placeholder="商品選択", options=[discord.SelectOption(label=n) for n in PRODUCTS])

            async def callback(self, interaction: discord.Interaction):
                await interaction.response.send_message(view=AdminProductView(self.values[0]), ephemeral=True)

        class AdminSelectView(View):
            def __init__(self):
                super().__init__(timeout=None)
                if PRODUCTS:
                    self.add_item(AdminProductSelect())

        class StockAddModal(Modal):
            def __init__(self, product):
                super().__init__(title="在庫追加")
                self.product = product
                self.txt = TextInput(label="改行で複数追加", style=discord.TextStyle.paragraph)
                self.add_item(self.txt)

            async def on_submit(self, interaction: discord.Interaction):
                items = [x.strip() for x in self.txt.value.split("\n") if x.strip()]
                PRODUCTS[self.product]["stock_list"].extend(items)
                save_products()
                save_info()  # 永続化
                await update_all_shop_messages()
                await interaction.response.send_message("追加完了", ephemeral=True)

        class StockRemoveModal(Modal):
            def __init__(self, product):
                super().__init__(title="在庫取り出し")
                self.product = product
                self.qty = TextInput(label="個数")
                self.add_item(self.qty)

            async def on_submit(self, interaction: discord.Interaction):
                q = int(self.qty.value)
                removed = [PRODUCTS[self.product]["stock_list"].pop(0) for _ in range(q)]
                save_products()
                save_info()  # 永続化
                await update_all_shop_messages()
                await interaction.response.send_message("取り出し:\n" + ",".join(removed), ephemeral=True)

        class PriceModal(Modal):
            def __init__(self, product):
                super().__init__(title="価格変更")
                self.product = product
                self.price = TextInput(label="新価格")
                self.add_item(self.price)

            async def on_submit(self, interaction: discord.Interaction):
                PRODUCTS[self.product]["price"] = int(self.price.value)
                save_products()
                save_info()  # 永続化
                await update_all_shop_messages()
                await interaction.response.send_message("変更完了", ephemeral=True)

        class AdminProductView(View):
            def __init__(self, product):
                super().__init__(timeout=None)
                self.product = product

            @discord.ui.button(label="在庫追加")
            async def add(self, i, b):
                await i.response.send_modal(StockAddModal(self.product))

            @discord.ui.button(label="在庫取り出し")
            async def rem(self, i, b):
                await i.response.send_modal(StockRemoveModal(self.product))

            @discord.ui.button(label="価格変更")
            async def price(self, i, b):
                await i.response.send_modal(PriceModal(self.product))

        # =========================
        # コマンド
        # =========================
        @bot.tree.command(name="shop")
        @app_commands.guilds(GUILD)
        async def shop(interaction: discord.Interaction):
            await interaction.response.send_message(embed=generate_shop_embed(), view=ShopView())
            msg = await interaction.original_response()
            shop_messages.append({"channel_id": msg.channel.id, "message_id": msg.id})
            save_shop_messages()
            save_info()  # 永続化

        @bot.tree.command(name="admin_manage")
        @app_commands.guilds(GUILD)
        async def admin_manage(interaction: discord.Interaction):
            await interaction.response.send_message("商品選択", view=AdminSelectView(), ephemeral=True)

        @bot.tree.command(name="add_product")
        @app_commands.guilds(GUILD)
        async def add_product_cmd(interaction: discord.Interaction, name: str, price: int):
            PRODUCTS[name] = {"price": price, "stock_list": []}
            save_products()
            save_info()
            await update_all_shop_messages()
            await interaction.response.send_message("追加完了")

        @bot.tree.command(name="delete_product")
        @app_commands.guilds(GUILD)
        async def delete_product_cmd(interaction: discord.Interaction):
            class Sel(Select):
                def __init__(self):
                    super().__init__(placeholder="削除する商品", options=[discord.SelectOption(label=n) for n in PRODUCTS])

                async def callback(self, interaction2):
                    product = self.values[0]
                    del PRODUCTS[product]
                    save_products()
                    save_info()
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
            bot.add_view(AdminSelectView())
            print("BOT起動")

        keep_alive()

        while True:
            try:
                print("Starting bot...")
                bot.run(os.getenv("TOKEN"))
            except Exception as e:
                print("Bot crashed:", e)
                print("Restarting in 10秒...")
                time.sleep(10)
