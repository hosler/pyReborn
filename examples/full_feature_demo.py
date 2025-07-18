#!/usr/bin/env python3
"""
Full Feature Demo - Demonstrates all PyReborn features including new GServer-v2 support

This example shows how to use:
- Item system (pickup, drop, chests)
- Combat system (damage, explosions, hit detection)
- NPC interactions (create, modify, trigger actions)
- High-precision movement
- Extended attributes
"""

import sys
import time
import logging
sys.path.insert(0, '..')

from pyreborn import RebornClient
from pyreborn.protocol.enums import LevelItemType, Direction, PlayerProp
from pyreborn.events import EventType

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class FullFeatureBot:
    """Bot that demonstrates all PyReborn features"""
    
    def __init__(self, host: str, port: int = 14900):
        # Create client with all extensions
        self.client = RebornClient(host, port)
        
        # Track stats
        self.items_collected = 0
        self.npcs_created = 0
        self.players_attacked = 0
        
        # Setup event handlers
        self._setup_events()
        
    def _setup_events(self):
        """Setup all event handlers"""
        # Basic events
        self.client.events.subscribe(EventType.LOGIN_SUCCESS, self._on_login)
        self.client.events.subscribe(EventType.LEVEL_ENTERED, self._on_level_entered)
        self.client.events.subscribe(EventType.PLAYER_ADDED, self._on_player_added)
        self.client.events.subscribe(EventType.CHAT_MESSAGE, self._on_chat)
        
        # New feature events
        self.client.events.subscribe(EventType.ITEM_SPAWNED, self._on_item_spawned)
        self.client.events.subscribe(EventType.PLAYER_HURT, self._on_player_hurt)
        self.client.events.subscribe(EventType.EXPLOSION, self._on_explosion)
        self.client.events.subscribe(EventType.NPC_ACTION, self._on_npc_action)
        self.client.events.subscribe(EventType.TRIGGER_RESPONSE, self._on_trigger_response)
        
    def _on_login(self, **kwargs):
        """Handle login success"""
        logger.info("✅ Login successful! Demonstrating all features...")
        
        # Set nickname with emoji
        self.client.set_nickname("🤖 FeatureBot")
        
        # Demonstrate high-precision movement
        self.client.move_to(30.5, 30.5)
        
        # Set extended attributes
        self._set_extended_attributes()
        
    def _on_level_entered(self, **kwargs):
        """Handle level entry"""
        level = kwargs.get('level')
        logger.info(f"📍 Entered level: {level.name if level else 'Unknown'}")
        
        # Wait a moment for level to load
        time.sleep(1)
        
        # Demonstrate features
        self._demonstrate_item_system()
        self._demonstrate_npc_system()
        self._demonstrate_combat_system()
        
    def _on_player_added(self, **kwargs):
        """Handle new player"""
        player = kwargs.get('player')
        if player and player.id != self.client.local_player.id:
            logger.info(f"👤 Player joined: {player.nickname}")
            
            # Greet them
            self.client.say(f"Hello {player.nickname}! I'm demonstrating PyReborn features!")
            
    def _on_chat(self, **kwargs):
        """Handle chat messages"""
        player = kwargs.get('player')
        message = kwargs.get('message', '')
        
        if not player or player.id == self.client.local_player.id:
            return
            
        # Respond to commands
        if message.lower() == "demo items":
            self._demonstrate_item_system()
        elif message.lower() == "demo combat":
            self._demonstrate_combat_system()
        elif message.lower() == "demo npcs":
            self._demonstrate_npc_system()
        elif message.lower() == "stats":
            self._show_stats()
            
    def _on_item_spawned(self, **kwargs):
        """Handle item spawn"""
        item = kwargs.get('item')
        if item:
            logger.info(f"💎 Item spawned: {item['type'].name} at ({item['x']}, {item['y']})")
            
            # Try to pick it up
            if self.client.pickup_item(item['x'], item['y']):
                self.items_collected += 1
                
    def _on_player_hurt(self, **kwargs):
        """Handle player damage"""
        attacker = kwargs.get('attacker_id')
        target = kwargs.get('target_id')
        damage = kwargs.get('damage')
        
        if target == self.client.local_player.id:
            logger.warning(f"💔 We were hurt by player {attacker} for {damage} damage!")
            # Retaliate
            self.client.hurt_player(attacker, 0.5)
            
    def _on_explosion(self, **kwargs):
        """Handle explosion"""
        x = kwargs.get('x', 0)
        y = kwargs.get('y', 0)
        logger.info(f"💥 Explosion at ({x}, {y})!")
        
    def _on_npc_action(self, **kwargs):
        """Handle NPC action"""
        npc_id = kwargs.get('npc_id')
        action = kwargs.get('action')
        logger.info(f"🎭 NPC {npc_id} performed action: {action}")
        
    def _on_trigger_response(self, **kwargs):
        """Handle trigger response"""
        action = kwargs.get('action')
        params = kwargs.get('params')
        logger.info(f"⚡ Trigger response: {action} -> {params}")
        
    def _set_extended_attributes(self):
        """Demonstrate extended GATTRIB support"""
        logger.info("📊 Setting extended attributes (GATTRIB 1-30)...")
        
        # Set some extended attributes
        for i in range(1, 11):
            attr_name = f"PLPROP_GATTRIB{i}"
            if hasattr(PlayerProp, attr_name):
                prop = getattr(PlayerProp, attr_name)
                self.client.set_player_prop(prop, f"Attr{i}")
                
        logger.info("✅ Extended attributes set!")
        
    def _demonstrate_item_system(self):
        """Demonstrate item features"""
        logger.info("\n🎮 DEMONSTRATING ITEM SYSTEM")
        
        # Drop some items
        logger.info("Dropping items...")
        self.client.drop_item(LevelItemType.GREENRUPEE, self.client.local_player.x + 2, self.client.local_player.y)
        self.client.drop_item(LevelItemType.HEART, self.client.local_player.x - 2, self.client.local_player.y)
        self.client.drop_item(LevelItemType.BOMB, self.client.local_player.x, self.client.local_player.y + 2)
        
        time.sleep(1)
        
        # Pick up nearby items
        logger.info("Picking up nearby items...")
        picked = self.client.items.pickup_nearby_items(radius=3.0)
        logger.info(f"Picked up {picked} items")
        
        # Try to open chests
        logger.info("Looking for chests...")
        level = self.client.level_manager.get_current_level()
        if level and level.chests:
            for chest in level.chests[:3]:  # Open up to 3 chests
                if self.client.open_chest(chest.x, chest.y):
                    logger.info(f"📦 Opened chest at ({chest.x}, {chest.y})")
                    time.sleep(0.5)
                    
        # Demonstrate throwing
        logger.info("Demonstrating throw mechanics...")
        self.client.set_carry_sprite("bush")
        time.sleep(0.5)
        self.client.throw_carried(power=0.8)
        logger.info("🌿 Threw carried bush!")
        
    def _demonstrate_npc_system(self):
        """Demonstrate NPC features"""
        logger.info("\n🎮 DEMONSTRATING NPC SYSTEM")
        
        # Create some NPCs
        logger.info("Creating NPCs...")
        
        # Friendly NPC
        npc1 = self.client.create_npc(
            self.client.local_player.x + 5,
            self.client.local_player.y,
            "npc1.png",
            "say Hello! I'm a friendly NPC!"
        )
        self.npcs_created += 1
        logger.info(f"Created friendly NPC with ID: {npc1}")
        
        # Shop NPC
        npc2 = self.client.create_npc(
            self.client.local_player.x - 5,
            self.client.local_player.y,
            "merchant.png",
            "showshop"
        )
        self.npcs_created += 1
        logger.info(f"Created shop NPC with ID: {npc2}")
        
        time.sleep(1)
        
        # Interact with NPCs
        logger.info("Interacting with NPCs...")
        nearby_npcs = self.client.npcs.find_nearby_npcs(radius=10.0)
        for npc in nearby_npcs[:2]:
            self.client.touch_npc(npc.id)
            time.sleep(0.5)
            
        # Trigger some actions
        logger.info("Sending trigger actions...")
        self.client.trigger_action("test", "param1,param2")
        self.client.trigger_action("servertime")
        self.client.trigger_action("playerstats", str(self.client.local_player.id))
        
    def _demonstrate_combat_system(self):
        """Demonstrate combat features"""
        logger.info("\n🎮 DEMONSTRATING COMBAT SYSTEM")
        
        # Create explosion
        logger.info("Creating explosion...")
        self.client.create_explosion(
            self.client.local_player.x + 5,
            self.client.local_player.y + 5,
            power=2.0,
            radius=4.0
        )
        
        # Check for hits
        logger.info("Checking hit detection...")
        hits = self.client.check_hit(
            self.client.local_player.x,
            self.client.local_player.y - 2,
            width=4.0,
            height=4.0
        )
        if hits:
            logger.info(f"⚔️ Hit {len(hits)} objects!")
            
        # Attack nearby players (carefully)
        for player_id, player in list(self.client._players.items())[:1]:  # Only first player
            if player_id != self.client.local_player.id:
                logger.info(f"Demonstrating combat on {player.nickname}...")
                
                # Sword attack
                hits = self.client.combat.sword_attack(reach=3.0)
                if hits:
                    logger.info(f"⚔️ Sword hit {len(hits)} targets!")
                    
                # Direct damage (small amount)
                self.client.hurt_player(player_id, 0.1)
                self.players_attacked += 1
                
                # Arrow attack
                self.client.combat.arrow_attack(player.x, player.y, power=0.5)
                
                break
                
        # Check our health
        current, maximum = self.client.combat.get_player_health()
        logger.info(f"❤️ Our health: {current}/{maximum}")
        
    def _show_stats(self):
        """Show bot statistics"""
        stats = f"""
📊 FeatureBot Statistics:
- Items Collected: {self.items_collected}
- NPCs Created: {self.npcs_created}  
- Players Attacked: {self.players_attacked}
- Position: ({self.client.local_player.x:.1f}, {self.client.local_player.y:.1f})
- Health: {self.client.local_player.cur_power}/{self.client.local_player.max_power}
        """
        
        for line in stats.strip().split('\n'):
            self.client.say(line)
            time.sleep(0.5)
            
    def run(self, username: str, password: str):
        """Run the bot"""
        try:
            # Connect
            logger.info(f"🔌 Connecting to {self.client.host}:{self.client.port}...")
            if not self.client.connect():
                logger.error("Failed to connect!")
                return
                
            # Login
            logger.info(f"🔑 Logging in as {username}...")
            if not self.client.login(username, password):
                logger.error("Failed to login!")
                return
                
            # Main loop
            logger.info("✅ Bot running! Commands: 'demo items', 'demo combat', 'demo npcs', 'stats'")
            
            while self.client.connected:
                time.sleep(0.1)
                
                # Periodic demonstrations
                if int(time.time()) % 60 == 0:  # Every minute
                    self._show_stats()
                    
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            if self.client.connected:
                self.client.disconnect()
                

def main():
    """Main entry point"""
    print("""
    ╔═══════════════════════════════════════════╗
    ║     PyReborn Full Feature Demo Bot        ║
    ║                                           ║
    ║  Demonstrates all GServer-v2 features:    ║
    ║  • Item System (pickup, drop, throw)      ║
    ║  • Combat System (damage, explosions)     ║
    ║  • NPC System (create, interact)          ║
    ║  • High-Precision Movement                ║
    ║  • Extended Attributes (GATTRIB 1-30)     ║
    ║  • Trigger Actions                        ║
    ╚═══════════════════════════════════════════╝
    """)
    
    # Get credentials
    if len(sys.argv) >= 3:
        username = sys.argv[1]
        password = sys.argv[2]
        host = sys.argv[3] if len(sys.argv) > 3 else "localhost"
    else:
        host = input("Server (default: localhost): ").strip() or "localhost"
        username = input("Username: ").strip()
        password = input("Password: ").strip()
        
    # Create and run bot
    bot = FullFeatureBot(host)
    bot.run(username, password)
    

if __name__ == "__main__":
    main()