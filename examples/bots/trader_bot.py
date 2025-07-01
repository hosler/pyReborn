#!/usr/bin/env python3
"""
Trader Bot - Simple trading system with inventory and prices
"""

from pyreborn import RebornClient
import json
import time
import logging
import random

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

class TraderBot:
    def __init__(self, client):
        self.client = client
        self.inventory = {
            'apples': {'stock': 50, 'price': 10, 'max': 100},
            'bread': {'stock': 30, 'price': 25, 'max': 50},
            'sword': {'stock': 5, 'price': 200, 'max': 10},
            'shield': {'stock': 3, 'price': 150, 'max': 8},
            'potion': {'stock': 20, 'price': 50, 'max': 40},
        }
        self.player_transactions = {}  # Track player purchase history
        self.last_restock = time.time()
        self.restock_interval = 60.0  # Restock every minute
        
    def get_inventory_display(self):
        """Get formatted inventory for display"""
        items = []
        for item, data in self.inventory.items():
            if data['stock'] > 0:
                items.append(f"{item}({data['stock']})=${data['price']}")
        return " | ".join(items[:3]) + "..."  # Show first 3 items
        
    def on_chat(self, event):
        """Handle trade commands"""
        player = event['player']
        message = event['message'].lower().strip()
        
        # Check for restock
        self.check_restock()
        
        if message == "!shop" or message == "!trade":
            self.show_shop_menu(player)
            
        elif message == "!inventory":
            self.client.set_chat(self.get_inventory_display())
            
        elif message.startswith("!buy "):
            self.handle_purchase(player, message)
            
        elif message.startswith("!sell "):
            self.handle_sale(player, message)
            
        elif message == "!prices":
            self.show_prices()
            
        elif message == "!help":
            self.client.set_chat("Commands: !shop, !buy <item> [amount], !sell <item>, !prices")
            
    def show_shop_menu(self, player):
        """Show available items"""
        self.client.set_chat(f"Welcome {player.nickname}! Type !buy <item> to purchase")
        time.sleep(0.5)
        
        # Show items with stock
        items_in_stock = []
        for item, data in self.inventory.items():
            if data['stock'] > 0:
                items_in_stock.append(f"{item}: ${data['price']} ({data['stock']} left)")
                
        if items_in_stock:
            # Show in batches to avoid chat limit
            self.client.set_chat(" | ".join(items_in_stock[:3]))
        else:
            self.client.set_chat("Sorry, I'm out of stock! Come back later.")
            
    def handle_purchase(self, player, message):
        """Process a purchase request"""
        parts = message.split()
        if len(parts) < 2:
            self.client.set_chat("Usage: !buy <item> [amount]")
            return
            
        item_name = parts[1]
        amount = 1
        
        if len(parts) > 2:
            try:
                amount = int(parts[2])
                amount = max(1, min(10, amount))  # Limit 1-10 per purchase
            except:
                amount = 1
                
        # Check if item exists
        if item_name not in self.inventory:
            self.client.set_chat(f"I don't sell {item_name}")
            return
            
        item = self.inventory[item_name]
        
        # Check stock
        if item['stock'] < amount:
            self.client.set_chat(f"Sorry, I only have {item['stock']} {item_name} left")
            return
            
        # Calculate total price
        total_price = item['price'] * amount
        
        # Process purchase (in a real game, would check player's money)
        item['stock'] -= amount
        
        # Track transaction
        if player.name not in self.player_transactions:
            self.player_transactions[player.name] = []
        self.player_transactions[player.name].append({
            'item': item_name,
            'amount': amount,
            'price': total_price,
            'time': time.time()
        })
        
        # Confirm purchase
        self.client.set_chat(f"Sold {amount} {item_name} to {player.nickname} for ${total_price}!")
        logging.info(f"Sale: {player.nickname} bought {amount} {item_name} for ${total_price}")
        
        # Apply item effect (visual only)
        if item_name == 'sword':
            self.client.set_chat("*hands over a shiny sword*")
        elif item_name == 'shield':
            self.client.set_chat("*gives you a sturdy shield*")
        elif item_name == 'potion':
            self.client.set_chat("*passes a glowing potion*")
            
    def handle_sale(self, player, message):
        """Handle players selling items to the trader"""
        parts = message.split()
        if len(parts) < 2:
            self.client.set_chat("Usage: !sell <item>")
            return
            
        item_name = parts[1]
        
        if item_name not in self.inventory:
            self.client.set_chat(f"I don't buy {item_name}")
            return
            
        item = self.inventory[item_name]
        
        # Check if we have room
        if item['stock'] >= item['max']:
            self.client.set_chat(f"Sorry, I have too many {item_name} already")
            return
            
        # Buy at 50% of sell price
        buy_price = item['price'] // 2
        
        # Process sale
        item['stock'] += 1
        self.client.set_chat(f"I'll buy your {item_name} for ${buy_price}")
        logging.info(f"Purchase: Bought {item_name} from {player.nickname} for ${buy_price}")
        
    def show_prices(self):
        """Show current prices"""
        price_list = []
        for item, data in self.inventory.items():
            sell_price = data['price']
            buy_price = sell_price // 2
            price_list.append(f"{item}: sell ${sell_price}, buy ${buy_price}")
            
        self.client.set_chat(" | ".join(price_list[:3]) + "...")
        
    def check_restock(self):
        """Periodically restock items"""
        current_time = time.time()
        if current_time - self.last_restock > self.restock_interval:
            self.restock_items()
            self.last_restock = current_time
            
    def restock_items(self):
        """Restock random items"""
        restocked = []
        for item, data in self.inventory.items():
            if data['stock'] < data['max']:
                # Random restock amount
                restock_amount = random.randint(1, 5)
                new_stock = min(data['stock'] + restock_amount, data['max'])
                if new_stock > data['stock']:
                    data['stock'] = new_stock
                    restocked.append(item)
                    
        if restocked:
            self.client.set_chat(f"*restocked {', '.join(restocked[:2])}*")
            logging.info(f"Restocked: {', '.join(restocked)}")
            
    def adjust_prices(self):
        """Adjust prices based on demand (optional feature)"""
        for item, data in self.inventory.items():
            # Lower price if overstocked
            if data['stock'] > data['max'] * 0.8:
                data['price'] = int(data['price'] * 0.9)
            # Raise price if low stock
            elif data['stock'] < data['max'] * 0.2:
                data['price'] = int(data['price'] * 1.1)

def main():
    client = RebornClient("localhost", 14900)
    
    # Create trader
    trader = TraderBot(client)
    
    # Subscribe to chat events
    client.events.subscribe('player_chat', trader.on_chat)
    
    # Connect and run
    if client.connect():
        logging.info("Connected to server")
        
        if client.login("hosler", "1234"):
            logging.info("Login successful")
            
            # Set appearance
            client.set_nickname("TraderBot")
            client.set_head_image("head4.png")
            client.set_body_image("body4.png")
            client.set_chat("Shop open! Say !shop to trade")
            
            # Move to market position
            client.move_to(35, 30)
            
            # Periodic announcements
            def announce_shop():
                announcements = [
                    "Fresh items for sale! Say !shop",
                    "Best prices in town! Type !shop",
                    f"Today's special: {random.choice(list(trader.inventory.keys()))}!",
                    "Buying and selling! Say !help",
                ]
                
                while client.connected:
                    time.sleep(30)  # Announce every 30 seconds
                    if client.connected:
                        msg = random.choice(announcements)
                        client.set_chat(msg)
                        
            import threading
            announce_thread = threading.Thread(target=announce_shop)
            announce_thread.daemon = True
            announce_thread.start()
            
            try:
                logging.info("TraderBot is open for business. Press Ctrl+C to stop.")
                while client.connected:
                    time.sleep(0.1)
            except KeyboardInterrupt:
                logging.info("Closing shop...")
            finally:
                client.disconnect()
        else:
            logging.error("Login failed")
    else:
        logging.error("Connection failed")

if __name__ == "__main__":
    main()