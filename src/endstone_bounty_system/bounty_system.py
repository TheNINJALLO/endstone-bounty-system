"""
Advanced Bounty System Plugin for Endstone
Features:
- Place bounties on players using the Money scoreboard
- Safe zones where bounties cannot be claimed
- PvP opt-in/opt-out system with cooldowns
- New player protection period
- Post-bounty-claim protection period
- Stackable bounties from multiple players
- Leaderboard system
"""

import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from endstone import ColorFormat, Player
from endstone.command import Command, CommandSender
from endstone.event import event_handler, PlayerDeathEvent, PlayerJoinEvent, PlayerMoveEvent, ActorDamageEvent, PlayerInteractEvent
from endstone.form import ActionForm, ModalForm, TextInput, Dropdown, Button, Label
from endstone.plugin import Plugin


class BountySystem(Plugin):
    api_version = "0.11"

    commands = {
        "bounty": {
            "description": "Open bounty menu or manage bounties",
            "usages": ["/bounty", "/bounty list", "/bounty opt", "/bounty bopt", "/bounty waive", "/bounty config", "/bounty remove"]
        },
        "safezone": {
            "description": "Manage safe zones",
            "usages": ["/safezone"]
        }
    }

    permissions = {
        "bounty.use": {
            "description": "Allows players to use bounty commands",
            "default": True
        },
        "bounty.admin": {
            "description": "Allows admins to manage safe zones",
            "default": "op"
        }
    }

    def __init__(self):
        super().__init__()
        self.data_file: Path = None
        self.config_file: Path = None

        # Data structures
        self.bounties: Dict[str, Dict] = {}  # {target_name: {total: int, contributors: {placer_name: amount}}}
        self.safe_zones: List[Dict] = []  # [{name, x1, y1, z1, x2, y2, z2, dimension, allow_pvp}]
        # Player data now tracks PvP and Bounty opt-in separately
        # pvp_enabled: Can attack/be attacked by other players
        # bounty_enabled: Can place/claim/have bounties (requires pvp_enabled)
        self.player_data: Dict[str, Dict] = {}
        # Track recent player attacks for fire damage attribution (fire damage comes after the initial hit)
        self.recent_attacks: Dict[str, Dict] = {}  # victim_name -> {attacker_name, timestamp}
        # Track safe zone PvP violations (strikes before kick)
        # Now stores {attacker_name: {"count": int, "last_strike": timestamp}}
        self.safezone_strikes: Dict[str, Dict] = {}
        # Debounce altar interactions to prevent menu opening multiple times
        self.altar_interactions: Dict[str, float] = {}  # player_name -> last_interaction_timestamp

        # Default configuration
        self.settings = {
            "pvp_opt_in_cooldown": 86400,  # 1 day in seconds
            "pvp_opt_out_cooldown": 259200,  # 3 days in seconds
            "bounty_opt_in_cooldown": 86400,  # 1 day in seconds
            "bounty_opt_out_cooldown": 259200,  # 3 days in seconds
            "new_player_protection": 259200,  # 3 days in seconds
            "post_bounty_protection": 259200,  # 3 days in seconds
            "new_player_waiver_cost": 1000,  # Cost to waive new player protection
            "death_protection_waiver_cost": 500,  # Cost to waive post-bounty protection
            "opt_in_waiver_cost": 1000,  # Cost to waive PvP opt-in cooldown
            "opt_out_waiver_cost": 500,  # Cost to waive PvP opt-out cooldown
            "bounty_opt_in_waiver_cost": 1000,  # Cost to waive bounty opt-in cooldown
            "bounty_opt_out_waiver_cost": 500,  # Cost to waive bounty opt-out cooldown
            "min_bounty_amount": 100,
            "money_objective": "Money",
            "force_pvp_enabled": False,  # If true, all players can attack each other (safe zones still apply)
            "safezone_strike_decay": 3600  # 1 hour in seconds - strikes reset after this period of no violations
        }

    def on_enable(self) -> None:
        """Called when the plugin is enabled"""
        self.logger.info("Enabling Bounty System Plugin...")

        # Setup data directory
        self.data_file = self.data_folder / "bounty_data.json"
        self.config_file = self.data_folder / "config.json"

        # Load configuration and data
        self.load_config()
        self.load_data()

        # Register event handlers
        self.register_events(self)

        self.logger.info("Bounty System Plugin enabled successfully!")

    def on_disable(self) -> None:
        """Called when the plugin is disabled"""
        self.save_data()
        self.logger.info("Bounty System Plugin disabled!")

    def load_config(self) -> None:
        """Load configuration from file or create default"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    loaded_config = json.load(f)
                    self.settings.update(loaded_config)
                self.logger.info("Configuration loaded successfully")
            except Exception as e:
                self.logger.error(f"Failed to load config: {e}")
        else:
            self.save_config()
            self.logger.info("Created default configuration file")

    def save_config(self) -> None:
        """Save configuration to file"""
        self.data_folder.mkdir(exist_ok=True)
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.settings, f, indent=4)
            self.logger.info("Configuration saved successfully")
        except Exception as e:
            self.logger.error(f"Failed to save config: {e}")

    def load_data(self) -> None:
        """Load bounty data from file"""
        if self.data_file.exists():
            try:
                with open(self.data_file, 'r') as f:
                    data = json.load(f)
                    self.bounties = data.get('bounties', {})
                    self.safe_zones = data.get('safe_zones', [])
                    self.player_data = data.get('player_data', {})
                self.logger.info("Bounty data loaded successfully")
            except Exception as e:
                self.logger.error(f"Failed to load data: {e}")

    def save_data(self) -> None:
        """Save bounty data to file"""
        self.data_folder.mkdir(exist_ok=True)
        try:
            data = {
                'bounties': self.bounties,
                'safe_zones': self.safe_zones,
                'player_data': self.player_data
            }
            with open(self.data_file, 'w') as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            self.logger.error(f"Failed to save data: {e}")

    def on_command(self, sender: CommandSender, command: Command, args: List[str]) -> bool:
        """Handle all plugin commands"""
        if command.name == "bounty":
            return self.handle_bounty_command(sender, args)
        elif command.name == "safezone":
            return self.handle_safezone_command(sender, args)
        return False

    def handle_bounty_command(self, sender: CommandSender, args: List[str]) -> bool:
        """Handle /bounty command"""
        if not isinstance(sender, Player):
            sender.send_message(ColorFormat.RED + "This command can only be used by players!")
            return True

        player = sender

        # Initialize player data if needed
        self.ensure_player_data(player.name)

        # Handle subcommands
        if len(args) > 0:
            subcmd = args[0].lower()

            if subcmd == "list":
                self.show_bounty_leaderboard(player)
                return True

            elif subcmd == "opt":
                self.toggle_pvp_opt(player)
                return True

            elif subcmd == "bopt":
                self.toggle_bounty_opt(player)
                return True

            elif subcmd == "waive":
                self.show_waive_cooldown_form(player)
                return True

            elif subcmd == "config":
                # Check if player has admin permission
                if not player.has_permission("bounty.admin"):
                    player.send_message(ColorFormat.RED + "You don't have permission to use this command!")
                    return True
                self.show_config_form(player)
                return True

            elif subcmd == "remove":
                # Check if player has admin permission
                if not player.has_permission("bounty.admin"):
                    player.send_message(ColorFormat.RED + "You don't have permission to use this command!")
                    return True
                self.show_remove_bounty_form(player)
                return True

        # No args or invalid arg - show bounty placement form
        self.show_bounty_form(player)
        return True

    def ensure_player_data(self, player_name: str) -> Dict:
        """Ensure player data exists and has all required fields"""
        if player_name not in self.player_data:
            self.player_data[player_name] = {
                "pvp_enabled": False,
                "bounty_enabled": False,
                "last_pvp_toggle": 0,
                "last_bounty_toggle": 0,
                "first_join": time.time(),
                "last_bounty_claimed": 0,
                "used_free_pvp_opt_in": False,
                "used_free_bounty_opt_in": False
            }
        else:
            # Ensure existing players have new fields
            player_info = self.player_data[player_name]
            if "bounty_enabled" not in player_info:
                player_info["bounty_enabled"] = player_info.get("pvp_enabled", False)  # Migrate: if had PvP, give bounty
            if "last_bounty_toggle" not in player_info:
                player_info["last_bounty_toggle"] = 0
            if "used_free_bounty_opt_in" not in player_info:
                player_info["used_free_bounty_opt_in"] = player_info.get("used_free_opt_in", False)  # Migrate
            if "used_free_pvp_opt_in" not in player_info:
                player_info["used_free_pvp_opt_in"] = player_info.get("used_free_opt_in", False)  # Migrate
        return self.player_data[player_name]

    def handle_safezone_command(self, sender: CommandSender, args: List[str]) -> bool:
        """Handle /safezone command"""
        # Check if sender has admin permission
        if not sender.has_permission("bounty.admin"):
            sender.send_message(ColorFormat.RED + "You don't have permission to use this command!")
            return True

        # Must be a player to use forms
        if not isinstance(sender, Player):
            sender.send_message(ColorFormat.RED + "This command can only be used by players!")
            return True

        player = sender

        # Show main safezone menu
        self.show_safezone_menu(player)
        return True

    def show_bounty_form(self, player: Player) -> None:
        """Show the bounty placement form"""
        player_name = player.name
        self.ensure_player_data(player_name)
        player_info = self.player_data[player_name]

        # Check if placer has Bounty enabled (which requires PvP enabled)
        if not player_info.get("bounty_enabled", False):
            if not player_info.get("pvp_enabled", False):
                player.send_message(ColorFormat.RED + "✗ You must be OPTED IN to PvP first!")
                player.send_message(ColorFormat.YELLOW + "Use /bounty opt to opt into PvP.")
            else:
                player.send_message(ColorFormat.RED + "✗ You must be OPTED IN to Bounties to place bounties!")
                player.send_message(ColorFormat.YELLOW + "Use /bounty bopt to opt into Bounties.")
            return

        # Get list of online players (excluding self) who have Bounty enabled
        online_players = []
        online_players_display = []
        for p in self.server.online_players:
            if p.name != player.name:
                self.ensure_player_data(p.name)
                # Only show players who have Bounty enabled
                if self.player_data[p.name].get("bounty_enabled", False):
                    online_players.append(p.name)
                    # Add visual indicator that they're opted in
                    online_players_display.append(f"{p.name} (✓ Bounty Opted In)")

        if len(online_players) == 0:
            player.send_message(ColorFormat.RED + "No other players with Bounties enabled are online!")
            player.send_message(ColorFormat.YELLOW + "You can only place bounties on players who are OPTED IN to Bounties.")
            return

        # Get player's current money
        current_money = self.get_money(player)

        form = ModalForm(
            title=f"Place a Bounty (Balance: {current_money})",
            controls=[
                Dropdown(
                    label="Target Player (Only Opted-In Players Shown)",
                    options=online_players_display,
                    default_index=0
                ),
                TextInput(
                    label=f"Bounty Amount (Min: {self.settings['min_bounty_amount']})",
                    placeholder="Enter amount",
                    default_value=str(self.settings['min_bounty_amount'])
                )
            ],
            submit_button="Place Bounty"
        )

        def on_submit(p: Player, json_str: str):
            try:
                data = json.loads(json_str)
                target_name = online_players[data[0]]
                amount_str = data[1]

                if not amount_str.isdigit():
                    p.send_message(ColorFormat.RED + "Invalid amount! Please enter a number.")
                    return

                amount = int(amount_str)

                if amount < self.settings['min_bounty_amount']:
                    p.send_message(ColorFormat.RED + f"Minimum bounty amount is {self.settings['min_bounty_amount']}!")
                    return

                # Check if target has post-bounty protection
                if target_name in self.player_data:
                    target_data = self.player_data[target_name]
                    last_claimed = target_data.get("last_bounty_claimed", 0)
                    protection_period = self.settings['post_bounty_protection']

                    if time.time() - last_claimed < protection_period:
                        remaining = int(protection_period - (time.time() - last_claimed))
                        days = remaining // 86400
                        hours = (remaining % 86400) // 3600
                        p.send_message(ColorFormat.RED + f"{target_name} has bounty protection for {days}d {hours}h more!")
                        return

                # Check if placer has enough money
                if not self.has_money(p, amount):
                    current_money = self.get_money(p)
                    p.send_message(ColorFormat.RED + f"You don't have enough money! You have {current_money}, need {amount}")
                    return

                # Remove money from placer
                self.remove_money(p.name, amount)

                # Add bounty
                if target_name not in self.bounties:
                    self.bounties[target_name] = {
                        "total": 0,
                        "contributors": {}
                    }

                # Stack bounty
                if p.name in self.bounties[target_name]["contributors"]:
                    self.bounties[target_name]["contributors"][p.name] += amount
                else:
                    self.bounties[target_name]["contributors"][p.name] = amount

                self.bounties[target_name]["total"] += amount

                self.save_data()

                # Notify
                p.send_message(ColorFormat.GREEN + f"Bounty of {amount} placed on {target_name}!")
                p.send_message(ColorFormat.YELLOW + f"Total bounty on {target_name}: {self.bounties[target_name]['total']}")

                # Notify target
                target_player = self.server.get_player(target_name)
                if target_player:
                    target_player.send_message(ColorFormat.RED + f"A bounty of {amount} has been placed on your head!")
                    target_player.send_message(ColorFormat.YELLOW + f"Total bounty: {self.bounties[target_name]['total']}")

            except Exception as e:
                p.send_message(ColorFormat.RED + f"Error placing bounty: {e}")
                self.logger.error(f"Error in bounty form: {e}")

        form.on_submit = on_submit
        player.send_form(form)

    def show_bounty_leaderboard(self, player: Player) -> None:
        """Show the bounty leaderboard via chat messages"""
        try:
            if len(self.bounties) == 0:
                player.send_message(ColorFormat.YELLOW + "No active bounties!")
                return

            # Sort bounties by total amount
            sorted_bounties = sorted(self.bounties.items(), key=lambda x: x[1]["total"], reverse=True)

            # Send leaderboard header
            player.send_message(ColorFormat.GOLD + "------- BOUNTY LEADERBOARD -------")
            
            # Send each bounty as a chat message
            rank = 1
            for target_name, bounty_data in sorted_bounties:
                total = bounty_data.get("total", 0)
                contributors = bounty_data.get("contributors", {})
                num_contributors = len(contributors)
                
                # Get top contributor (if any)
                if contributors:
                    top_placer = max(contributors.items(), key=lambda x: x[1])
                    top_info = f"Top: {top_placer[0]} ({top_placer[1]})"
                else:
                    top_info = "No contributors"
                
                player.send_message(
                    f"{ColorFormat.YELLOW}#{rank} {ColorFormat.GOLD}{target_name}: "
                    f"{ColorFormat.GREEN}{total} coins"
                )
                player.send_message(
                    f"  {ColorFormat.GRAY}Contributors: {num_contributors} | {top_info}"
                )
                rank += 1
            
            player.send_message(ColorFormat.GOLD + "----------------------------------")
        except Exception as e:
            player.send_message(ColorFormat.RED + "Error loading leaderboard!")
            self.logger.error(f"Leaderboard error: {e}")


    def refund_and_remove_bounty(self, target_name: str, notify_contributors: bool = True) -> Dict:
        """
        Refund all contributors for a bounty and remove it from the system.
        Returns dict with: refunded (bool), total (int), contributors (int)
        """
        result = {"refunded": False, "total": 0, "contributors": 0}
        
        if target_name not in self.bounties:
            return result
        
        bounty_data = self.bounties[target_name]
        total_refunded = bounty_data["total"]
        contributors = bounty_data["contributors"]
        num_contributors = len(contributors)
        
        # Refund each contributor
        for placer_name, amount in contributors.items():
            self.add_money(placer_name, amount)
            
            # Notify online contributors about their refund
            if notify_contributors:
                placer = self.server.get_player(placer_name)
                if placer:
                    placer.send_message(ColorFormat.GOLD + f"Bounty refund: {amount} coins returned!")
                    placer.send_message(ColorFormat.YELLOW + f"The bounty on {target_name} has been removed.")
        
        # Remove the bounty from the system
        del self.bounties[target_name]
        self.save_data()
        
        result["refunded"] = True
        result["total"] = total_refunded
        result["contributors"] = num_contributors
        
        self.logger.info(f"Refunded bounty on {target_name}: {total_refunded} coins to {num_contributors} contributors")
        return result

    def show_remove_bounty_form(self, player: Player) -> None:
        """Show form for operators to remove bounties from the system"""
        if len(self.bounties) == 0:
            player.send_message(ColorFormat.YELLOW + "No active bounties to remove!")
            return
        
        # Build list of bounties
        bounty_list = []
        bounty_display = []
        for target_name, bounty_data in sorted(self.bounties.items(), key=lambda x: x[1]["total"], reverse=True):
            bounty_list.append(target_name)
            total = bounty_data["total"]
            num_contributors = len(bounty_data["contributors"])
            bounty_display.append(f"{target_name} - {total} coins ({num_contributors} contributor(s))")
        
        form = ModalForm(
            title="Remove Bounty (Admin)",
            controls=[
                Dropdown(
                    label="Select bounty to remove and refund",
                    options=bounty_display,
                    default_index=0
                )
            ],
            submit_button="Remove & Refund"
        )
        
        def on_submit(p: Player, json_str: str):
            try:
                data = json.loads(json_str)
                selected_index = data[0]
                target_name = bounty_list[selected_index]
                
                # Get bounty info before removing
                bounty_info = self.bounties.get(target_name, {})
                total = bounty_info.get("total", 0)
                
                # Refund and remove the bounty
                result = self.refund_and_remove_bounty(target_name, notify_contributors=True)
                
                if result["refunded"]:
                    p.send_message(ColorFormat.GREEN + f"✓ Bounty on {target_name} removed!")
                    p.send_message(ColorFormat.YELLOW + f"Refunded {result['total']} coins to {result['contributors']} contributor(s).")
                    
                    # Notify the target if online
                    target_player = self.server.get_player(target_name)
                    if target_player:
                        target_player.send_message(ColorFormat.GOLD + "An operator has removed the bounty on you!")
                        target_player.send_message(ColorFormat.YELLOW + f"Contributors have been refunded {result['total']} coins.")
                else:
                    p.send_message(ColorFormat.RED + f"Failed to remove bounty on {target_name}.")
                    
            except Exception as e:
                p.send_message(ColorFormat.RED + f"Error removing bounty: {e}")
                self.logger.error(f"Error in remove bounty form: {e}")
        
        form.on_submit = on_submit
        player.send_form(form)

    def toggle_pvp_opt(self, player: Player) -> None:
        """Toggle PvP opt-in/opt-out with cooldown"""
        player_name = player.name
        player_info = self.ensure_player_data(player_name)
        current_time = time.time()
        last_toggle = player_info.get("last_pvp_toggle", 0)

        # Check if this is the first time opting in (FREE!)
        if not player_info["pvp_enabled"] and not player_info.get("used_free_pvp_opt_in", False):
            # First opt-in is FREE - no cooldown check!
            player_info["pvp_enabled"] = True
            player_info["last_pvp_toggle"] = current_time
            player_info["used_free_pvp_opt_in"] = True
            self.save_data()
            player.send_message(ColorFormat.GREEN + "✓ PvP OPTED IN!")
            player.send_message(ColorFormat.YELLOW + "You can now attack and be attacked by other players.")
            player.send_message(ColorFormat.YELLOW + "Use /bounty bopt to also opt into Bounties.")
            player.send_message(ColorFormat.GOLD + "(First PvP opt-in was FREE!)")
            return

        # Check cooldown for all other toggles
        if player_info["pvp_enabled"]:
            cooldown = self.settings['pvp_opt_out_cooldown']
        else:
            cooldown = self.settings['pvp_opt_in_cooldown']

        time_since_toggle = current_time - last_toggle

        if time_since_toggle < cooldown:
            # Show cooldown message
            remaining = int(cooldown - time_since_toggle)
            days = remaining // 86400
            hours = (remaining % 86400) // 3600
            minutes = (remaining % 3600) // 60

            if player_info["pvp_enabled"]:
                player.send_message(
                    ColorFormat.RED + f"PvP opt-out cooldown active! "
                    f"Wait {days}d {hours}h {minutes}m or use /bounty waive"
                )
            else:
                player.send_message(
                    ColorFormat.RED + f"PvP opt-in cooldown active! "
                    f"Wait {days}d {hours}h {minutes}m or use /bounty waive"
                )
            return

        # Toggle PvP status
        player_info["pvp_enabled"] = not player_info["pvp_enabled"]
        player_info["last_pvp_toggle"] = current_time

        # If opting out of PvP, also disable bounty
        if not player_info["pvp_enabled"]:
            if player_info.get("bounty_enabled", False):
                player_info["bounty_enabled"] = False
                player.send_message(ColorFormat.YELLOW + "Bounty participation also disabled (requires PvP).")

        self.save_data()

        if player_info["pvp_enabled"]:
            player.send_message(ColorFormat.GREEN + "✓ PvP OPTED IN!")
            player.send_message(ColorFormat.YELLOW + "You can now attack and be attacked by other players.")
            player.send_message(ColorFormat.YELLOW + "Use /bounty bopt to also opt into Bounties.")
        else:
            player.send_message(ColorFormat.RED + "✗ PvP OPTED OUT!")
            player.send_message(ColorFormat.YELLOW + "You are now protected from PvP combat.")

    def toggle_bounty_opt(self, player: Player) -> None:
        """Toggle Bounty opt-in/opt-out with cooldown (requires PvP to be enabled)"""
        player_name = player.name
        player_info = self.ensure_player_data(player_name)
        current_time = time.time()

        # Check if player has PvP enabled first
        if not player_info.get("pvp_enabled", False):
            player.send_message(ColorFormat.RED + "✗ You must be OPTED IN to PvP first!")
            player.send_message(ColorFormat.YELLOW + "Use /bounty opt to opt into PvP, then use /bounty bopt for Bounties.")
            return

        last_toggle = player_info.get("last_bounty_toggle", 0)

        # Check if this is the first time opting in (FREE!)
        if not player_info.get("bounty_enabled", False) and not player_info.get("used_free_bounty_opt_in", False):
            # First opt-in is FREE - no cooldown check!
            player_info["bounty_enabled"] = True
            player_info["last_bounty_toggle"] = current_time
            player_info["used_free_bounty_opt_in"] = True
            self.save_data()
            player.send_message(ColorFormat.GREEN + "✓ BOUNTY OPTED IN!")
            player.send_message(ColorFormat.YELLOW + "You can now place and claim bounties.")
            player.send_message(ColorFormat.YELLOW + "Other players can place bounties on you.")
            player.send_message(ColorFormat.GOLD + "(First Bounty opt-in was FREE!)")
            return

        # Check cooldown for all other toggles
        if player_info.get("bounty_enabled", False):
            cooldown = self.settings['bounty_opt_out_cooldown']
        else:
            cooldown = self.settings['bounty_opt_in_cooldown']

        time_since_toggle = current_time - last_toggle

        if time_since_toggle < cooldown:
            # Show cooldown message
            remaining = int(cooldown - time_since_toggle)
            days = remaining // 86400
            hours = (remaining % 86400) // 3600
            minutes = (remaining % 3600) // 60

            if player_info.get("bounty_enabled", False):
                player.send_message(
                    ColorFormat.RED + f"Bounty opt-out cooldown active! "
                    f"Wait {days}d {hours}h {minutes}m or use /bounty waive"
                )
            else:
                player.send_message(
                    ColorFormat.RED + f"Bounty opt-in cooldown active! "
                    f"Wait {days}d {hours}h {minutes}m or use /bounty waive"
                )
            return

        # Toggle Bounty status
        player_info["bounty_enabled"] = not player_info.get("bounty_enabled", False)
        player_info["last_bounty_toggle"] = current_time

        self.save_data()

        if player_info["bounty_enabled"]:
            player.send_message(ColorFormat.GREEN + "✓ BOUNTY OPTED IN!")
            player.send_message(ColorFormat.YELLOW + "You can now place and claim bounties.")
            player.send_message(ColorFormat.YELLOW + "Other players can place bounties on you.")
        else:
            player.send_message(ColorFormat.RED + "✗ BOUNTY OPTED OUT!")
            player.send_message(ColorFormat.YELLOW + "You are now protected from bounty hunters.")
            player.send_message(ColorFormat.YELLOW + "You cannot place or claim bounties while opted out.")
            player.send_message(ColorFormat.GRAY + "(You can still participate in PvP)")
            
            # Refund any active bounty on this player
            refund_result = self.refund_and_remove_bounty(player_name)
            if refund_result["refunded"]:
                player.send_message(ColorFormat.GOLD + f"Your bounty of {refund_result['total']} coins has been cleared!")
                player.send_message(ColorFormat.YELLOW + f"{refund_result['contributors']} contributor(s) have been refunded.")


    def show_waive_cooldown_form(self, player: Player) -> None:
        """Show form to waive protection cooldowns"""
        player_name = player.name
        player_info = self.ensure_player_data(player_name)
        current_time = time.time()

        # Check new player protection
        first_join = player_info.get("first_join", current_time)
        new_player_protection = self.settings['new_player_protection']
        new_player_remaining = new_player_protection - (current_time - first_join)
        has_new_player_protection = new_player_remaining > 0

        # Check post-bounty protection
        last_bounty_claimed = player_info.get("last_bounty_claimed", 0)
        post_bounty_protection = self.settings['post_bounty_protection']
        post_bounty_remaining = post_bounty_protection - (current_time - last_bounty_claimed)
        has_post_bounty_protection = post_bounty_remaining > 0

        # Check PvP toggle cooldowns
        last_pvp_toggle = player_info.get("last_pvp_toggle", 0)
        is_pvp_enabled = player_info.get("pvp_enabled", False)

        # Check PvP opt-in cooldown (if player is NOT opted in and has a cooldown)
        pvp_opt_in_cooldown = self.settings['pvp_opt_in_cooldown']
        pvp_opt_in_remaining = pvp_opt_in_cooldown - (current_time - last_pvp_toggle)
        has_pvp_opt_in_cooldown = not is_pvp_enabled and pvp_opt_in_remaining > 0

        # Check PvP opt-out cooldown (if player IS opted in and has a cooldown)
        pvp_opt_out_cooldown = self.settings['pvp_opt_out_cooldown']
        pvp_opt_out_remaining = pvp_opt_out_cooldown - (current_time - last_pvp_toggle)
        has_pvp_opt_out_cooldown = is_pvp_enabled and pvp_opt_out_remaining > 0

        # Check Bounty toggle cooldowns
        last_bounty_toggle = player_info.get("last_bounty_toggle", 0)
        is_bounty_enabled = player_info.get("bounty_enabled", False)

        # Check Bounty opt-in cooldown (if player is NOT opted in and has a cooldown)
        bounty_opt_in_cooldown = self.settings['bounty_opt_in_cooldown']
        bounty_opt_in_remaining = bounty_opt_in_cooldown - (current_time - last_bounty_toggle)
        has_bounty_opt_in_cooldown = not is_bounty_enabled and bounty_opt_in_remaining > 0 and is_pvp_enabled

        # Check Bounty opt-out cooldown (if player IS opted in and has a cooldown)
        bounty_opt_out_cooldown = self.settings['bounty_opt_out_cooldown']
        bounty_opt_out_remaining = bounty_opt_out_cooldown - (current_time - last_bounty_toggle)
        has_bounty_opt_out_cooldown = is_bounty_enabled and bounty_opt_out_remaining > 0

        # Build content
        content = "Waive your protection/cooldowns:\n\n"

        if has_new_player_protection:
            days = int(new_player_remaining // 86400)
            hours = int((new_player_remaining % 86400) // 3600)
            content += f"{ColorFormat.YELLOW}⚠ New Player Protection:{ColorFormat.RESET}\n"
            content += f"  {ColorFormat.GRAY}You are a new player!{ColorFormat.RESET}\n"
            content += f"  Remaining: {days}d {hours}h\n"
            content += f"  Cost to waive: {self.settings['new_player_waiver_cost']} coins\n\n"

        if has_post_bounty_protection:
            days = int(post_bounty_remaining // 86400)
            hours = int((post_bounty_remaining % 86400) // 3600)
            content += f"{ColorFormat.YELLOW}Post-Death Protection:{ColorFormat.RESET}\n"
            content += f"  Remaining: {days}d {hours}h\n"
            content += f"  Cost to waive: {self.settings['death_protection_waiver_cost']} coins\n\n"

        if has_pvp_opt_in_cooldown:
            days = int(pvp_opt_in_remaining // 86400)
            hours = int((pvp_opt_in_remaining % 86400) // 3600)
            minutes = int((pvp_opt_in_remaining % 3600) // 60)
            content += f"{ColorFormat.YELLOW}PvP Opt-In Cooldown:{ColorFormat.RESET}\n"
            content += f"  Remaining: {days}d {hours}h {minutes}m\n"
            content += f"  Cost to waive: {self.settings['opt_in_waiver_cost']} coins\n\n"

        if has_pvp_opt_out_cooldown:
            days = int(pvp_opt_out_remaining // 86400)
            hours = int((pvp_opt_out_remaining % 86400) // 3600)
            minutes = int((pvp_opt_out_remaining % 3600) // 60)
            content += f"{ColorFormat.YELLOW}PvP Opt-Out Cooldown:{ColorFormat.RESET}\n"
            content += f"  Remaining: {days}d {hours}h {minutes}m\n"
            content += f"  Cost to waive: {self.settings['opt_out_waiver_cost']} coins\n\n"

        if has_bounty_opt_in_cooldown:
            days = int(bounty_opt_in_remaining // 86400)
            hours = int((bounty_opt_in_remaining % 86400) // 3600)
            minutes = int((bounty_opt_in_remaining % 3600) // 60)
            content += f"{ColorFormat.YELLOW}Bounty Opt-In Cooldown:{ColorFormat.RESET}\n"
            content += f"  Remaining: {days}d {hours}h {minutes}m\n"
            content += f"  Cost to waive: {self.settings['bounty_opt_in_waiver_cost']} coins\n\n"

        if has_bounty_opt_out_cooldown:
            days = int(bounty_opt_out_remaining // 86400)
            hours = int((bounty_opt_out_remaining % 86400) // 3600)
            minutes = int((bounty_opt_out_remaining % 3600) // 60)
            content += f"{ColorFormat.YELLOW}Bounty Opt-Out Cooldown:{ColorFormat.RESET}\n"
            content += f"  Remaining: {days}d {hours}h {minutes}m\n"
            content += f"  Cost to waive: {self.settings['bounty_opt_out_waiver_cost']} coins\n\n"

        has_any = (has_new_player_protection or has_post_bounty_protection or
                   has_pvp_opt_in_cooldown or has_pvp_opt_out_cooldown or
                   has_bounty_opt_in_cooldown or has_bounty_opt_out_cooldown)
        if not has_any:
            player.send_message(ColorFormat.YELLOW + "You have no active protections or cooldowns to waive!")
            return

        # Get player's current money
        current_money = self.get_money(player)
        content += f"{ColorFormat.GREEN}Your Balance:{ColorFormat.RESET} {current_money} coins"

        # Create buttons for available waivers
        buttons = []
        if has_new_player_protection:
            buttons.append(Button(text=f"Waive New Player Protection ({self.settings['new_player_waiver_cost']} coins)"))
        if has_post_bounty_protection:
            buttons.append(Button(text=f"Waive Post-Death Protection ({self.settings['death_protection_waiver_cost']} coins)"))
        if has_pvp_opt_in_cooldown:
            buttons.append(Button(text=f"Waive PvP Opt-In Cooldown ({self.settings['opt_in_waiver_cost']} coins)"))
        if has_pvp_opt_out_cooldown:
            buttons.append(Button(text=f"Waive PvP Opt-Out Cooldown ({self.settings['opt_out_waiver_cost']} coins)"))
        if has_bounty_opt_in_cooldown:
            buttons.append(Button(text=f"Waive Bounty Opt-In Cooldown ({self.settings['bounty_opt_in_waiver_cost']} coins)"))
        if has_bounty_opt_out_cooldown:
            buttons.append(Button(text=f"Waive Bounty Opt-Out Cooldown ({self.settings['bounty_opt_out_waiver_cost']} coins)"))

        form = ActionForm(
            title="Waive Protection/Cooldowns",
            content=content,
            buttons=buttons
        )

        def on_submit(p: Player, selection: int):
            # Determine which protection was selected
            button_index = 0
            if has_new_player_protection and selection == button_index:
                self.waive_new_player_protection(p)
                return
            if has_new_player_protection:
                button_index += 1

            if has_post_bounty_protection and selection == button_index:
                self.waive_post_bounty_protection(p)
                return
            if has_post_bounty_protection:
                button_index += 1

            if has_pvp_opt_in_cooldown and selection == button_index:
                self.waive_pvp_opt_in_cooldown(p)
                return
            if has_pvp_opt_in_cooldown:
                button_index += 1

            if has_pvp_opt_out_cooldown and selection == button_index:
                self.waive_pvp_opt_out_cooldown(p)
                return
            if has_pvp_opt_out_cooldown:
                button_index += 1

            if has_bounty_opt_in_cooldown and selection == button_index:
                self.waive_bounty_opt_in_cooldown(p)
                return
            if has_bounty_opt_in_cooldown:
                button_index += 1

            if has_bounty_opt_out_cooldown and selection == button_index:
                self.waive_bounty_opt_out_cooldown(p)
                return

        form.on_submit = on_submit
        player.send_form(form)

    def waive_new_player_protection(self, player: Player) -> None:
        """Waive new player protection for a cost"""
        player_name = player.name
        cost = self.settings['new_player_waiver_cost']

        # Check if player has enough money
        if not self.has_money(player, cost):
            current_money = self.get_money(player)
            player.send_message(
                ColorFormat.RED + f"Insufficient funds! You have {current_money} but need {cost} coins."
            )
            return

        # Check if they still have protection
        player_info = self.player_data[player_name]
        current_time = time.time()
        first_join = player_info["first_join"]
        new_player_protection = self.settings['new_player_protection']

        if current_time - first_join >= new_player_protection:
            player.send_message(ColorFormat.YELLOW + "You no longer have new player protection!")
            return

        # Deduct money
        self.deduct_money(player, cost)

        # Set first_join to a time that makes protection expired
        player_info["first_join"] = current_time - new_player_protection - 1
        self.save_data()

        player.send_message(
            ColorFormat.GREEN + f"New player protection waived! You are now vulnerable to bounty hunters. (-{cost} coins)"
        )

    def waive_post_bounty_protection(self, player: Player) -> None:
        """Waive post-bounty protection for a cost"""
        player_name = player.name
        cost = self.settings['death_protection_waiver_cost']

        # Check if player has enough money
        if not self.has_money(player, cost):
            current_money = self.get_money(player)
            player.send_message(
                ColorFormat.RED + f"Insufficient funds! You have {current_money} but need {cost} coins."
            )
            return

        # Check if they still have protection
        player_info = self.player_data[player_name]
        current_time = time.time()
        last_bounty_claimed = player_info.get("last_bounty_claimed", 0)
        post_bounty_protection = self.settings['post_bounty_protection']

        if current_time - last_bounty_claimed >= post_bounty_protection:
            player.send_message(ColorFormat.YELLOW + "You no longer have post-death protection!")
            return

        # Deduct money
        self.deduct_money(player, cost)

        # Set last_bounty_claimed to a time that makes protection expired
        player_info["last_bounty_claimed"] = current_time - post_bounty_protection - 1
        self.save_data()

        player.send_message(
            ColorFormat.GREEN + f"Post-death protection waived! You are now vulnerable to bounty hunters. (-{cost} coins)"
        )

    def waive_pvp_opt_in_cooldown(self, player: Player) -> None:
        """Waive PvP opt-in cooldown to enable PvP immediately"""
        player_name = player.name
        player_info = self.ensure_player_data(player_name)
        current_time = time.time()
        cost = self.settings['opt_in_waiver_cost']

        # Check if player is already opted in
        if player_info.get("pvp_enabled", False):
            player.send_message(ColorFormat.YELLOW + "You are already opted into PvP!")
            return

        # Check if they have a cooldown
        last_toggle = player_info.get("last_pvp_toggle", 0)
        opt_in_cooldown = self.settings['pvp_opt_in_cooldown']
        time_since_toggle = current_time - last_toggle

        if time_since_toggle >= opt_in_cooldown:
            player.send_message(ColorFormat.YELLOW + "You don't have a PvP opt-in cooldown! Use /bounty opt to enable PvP.")
            return

        # Check if player has enough money
        if not self.has_money(player, cost):
            current_money = self.get_money(player)
            player.send_message(
                ColorFormat.RED + f"Insufficient funds! You have {current_money} but need {cost} coins."
            )
            return

        # Deduct money
        self.deduct_money(player, cost)

        # Enable PvP
        player_info["pvp_enabled"] = True
        player_info["last_pvp_toggle"] = current_time
        self.save_data()

        player.send_message(
            ColorFormat.GREEN + f"PvP opt-in cooldown waived! PvP enabled! (-{cost} coins)"
        )

    def waive_pvp_opt_out_cooldown(self, player: Player) -> None:
        """Waive PvP opt-out cooldown to disable PvP immediately"""
        player_name = player.name
        player_info = self.ensure_player_data(player_name)
        current_time = time.time()
        cost = self.settings['opt_out_waiver_cost']

        # Check if player is already opted out
        if not player_info.get("pvp_enabled", False):
            player.send_message(ColorFormat.YELLOW + "You are already opted out of PvP!")
            return

        # Check if they have a cooldown
        last_toggle = player_info.get("last_pvp_toggle", 0)
        opt_out_cooldown = self.settings['pvp_opt_out_cooldown']
        time_since_toggle = current_time - last_toggle

        if time_since_toggle >= opt_out_cooldown:
            player.send_message(ColorFormat.YELLOW + "You don't have a PvP opt-out cooldown! Use /bounty opt to disable PvP.")
            return

        # Check if player has enough money
        if not self.has_money(player, cost):
            current_money = self.get_money(player)
            player.send_message(
                ColorFormat.RED + f"Insufficient funds! You have {current_money} but need {cost} coins."
            )
            return

        # Deduct money
        self.deduct_money(player, cost)

        # Disable PvP and also disable bounty
        player_info["pvp_enabled"] = False
        player_info["bounty_enabled"] = False
        player_info["last_pvp_toggle"] = current_time
        self.save_data()

        player.send_message(
            ColorFormat.GREEN + f"PvP opt-out cooldown waived! PvP disabled! (-{cost} coins)"
        )

    def waive_bounty_opt_in_cooldown(self, player: Player) -> None:
        """Waive Bounty opt-in cooldown to enable Bounty immediately"""
        player_name = player.name
        player_info = self.ensure_player_data(player_name)
        current_time = time.time()
        cost = self.settings['bounty_opt_in_waiver_cost']

        # Check if player has PvP enabled
        if not player_info.get("pvp_enabled", False):
            player.send_message(ColorFormat.RED + "You must have PvP enabled first!")
            return

        # Check if player is already opted in
        if player_info.get("bounty_enabled", False):
            player.send_message(ColorFormat.YELLOW + "You are already opted into Bounties!")
            return

        # Check if they have a cooldown
        last_toggle = player_info.get("last_bounty_toggle", 0)
        opt_in_cooldown = self.settings['bounty_opt_in_cooldown']
        time_since_toggle = current_time - last_toggle

        if time_since_toggle >= opt_in_cooldown:
            player.send_message(ColorFormat.YELLOW + "You don't have a Bounty opt-in cooldown! Use /bounty bopt to enable Bounties.")
            return

        # Check if player has enough money
        if not self.has_money(player, cost):
            current_money = self.get_money(player)
            player.send_message(
                ColorFormat.RED + f"Insufficient funds! You have {current_money} but need {cost} coins."
            )
            return

        # Deduct money
        self.deduct_money(player, cost)

        # Enable Bounty
        player_info["bounty_enabled"] = True
        player_info["last_bounty_toggle"] = current_time
        self.save_data()

        player.send_message(
            ColorFormat.GREEN + f"Bounty opt-in cooldown waived! Bounties enabled! (-{cost} coins)"
        )

    def waive_bounty_opt_out_cooldown(self, player: Player) -> None:
        """Waive Bounty opt-out cooldown to disable Bounty immediately"""
        player_name = player.name
        player_info = self.ensure_player_data(player_name)
        current_time = time.time()
        cost = self.settings['bounty_opt_out_waiver_cost']

        # Check if player is already opted out
        if not player_info.get("bounty_enabled", False):
            player.send_message(ColorFormat.YELLOW + "You are already opted out of Bounties!")
            return

        # Check if they have a cooldown
        last_toggle = player_info.get("last_bounty_toggle", 0)
        opt_out_cooldown = self.settings['bounty_opt_out_cooldown']
        time_since_toggle = current_time - last_toggle

        if time_since_toggle >= opt_out_cooldown:
            player.send_message(ColorFormat.YELLOW + "You don't have a Bounty opt-out cooldown! Use /bounty bopt to disable Bounties.")
            return

        # Check if player has enough money
        if not self.has_money(player, cost):
            current_money = self.get_money(player)
            player.send_message(
                ColorFormat.RED + f"Insufficient funds! You have {current_money} but need {cost} coins."
            )
            return

        # Deduct money
        self.deduct_money(player, cost)

        # Disable Bounty
        player_info["bounty_enabled"] = False
        player_info["last_bounty_toggle"] = current_time
        self.save_data()

        player.send_message(
            ColorFormat.GREEN + f"Bounty opt-out cooldown waived! Bounties disabled! (-{cost} coins)"
        )

    def show_config_form(self, player: Player) -> None:
        """Show configuration form for admins - Page 1 (General Settings)"""
        form = ModalForm(
            title="Bounty System Config - General",
            controls=[
                TextInput(
                    label="New Player Protection (days)",
                    placeholder="3",
                    default_value=str(self.settings['new_player_protection'] // 86400)
                ),
                TextInput(
                    label="Post-Death Protection (days)",
                    placeholder="3",
                    default_value=str(self.settings['post_bounty_protection'] // 86400)
                ),
                TextInput(
                    label="PvP Opt-In Cooldown (days)",
                    placeholder="1",
                    default_value=str(self.settings['pvp_opt_in_cooldown'] // 86400)
                ),
                TextInput(
                    label="PvP Opt-Out Cooldown (days)",
                    placeholder="3",
                    default_value=str(self.settings['pvp_opt_out_cooldown'] // 86400)
                ),
                TextInput(
                    label="Bounty Opt-In Cooldown (days)",
                    placeholder="1",
                    default_value=str(self.settings['bounty_opt_in_cooldown'] // 86400)
                ),
                TextInput(
                    label="Bounty Opt-Out Cooldown (days)",
                    placeholder="3",
                    default_value=str(self.settings['bounty_opt_out_cooldown'] // 86400)
                ),
                TextInput(
                    label="Minimum Bounty Amount",
                    placeholder="100",
                    default_value=str(self.settings['min_bounty_amount'])
                ),
                Dropdown(
                    label="Force PvP Mode (All players can attack each other)",
                    options=["Disabled", "Enabled"],
                    default_index=1 if self.settings['force_pvp_enabled'] else 0
                )
            ]
        )

        def on_submit(p: Player, data):
            try:
                self.logger.info(f"Config form data type: {type(data)}, content: {data}")

                if isinstance(data, str):
                    import json
                    values = json.loads(data)
                elif isinstance(data, (list, tuple)):
                    values = data
                else:
                    values = list(data)

                new_player_protection_days = int(values[0]) if values[0] and str(values[0]).strip() else 3
                post_death_protection_days = int(values[1]) if values[1] and str(values[1]).strip() else 3
                pvp_opt_in_days = int(values[2]) if values[2] and str(values[2]).strip() else 1
                pvp_opt_out_days = int(values[3]) if values[3] and str(values[3]).strip() else 3
                bounty_opt_in_days = int(values[4]) if values[4] and str(values[4]).strip() else 1
                bounty_opt_out_days = int(values[5]) if values[5] and str(values[5]).strip() else 3
                min_bounty = int(values[6]) if values[6] and str(values[6]).strip() else 100
                force_pvp = values[7] == 1

                if (new_player_protection_days < 0 or post_death_protection_days < 0 or
                    pvp_opt_in_days < 0 or pvp_opt_out_days < 0 or
                    bounty_opt_in_days < 0 or bounty_opt_out_days < 0 or min_bounty < 0):
                    p.send_message(ColorFormat.RED + "All values must be positive!")
                    return

                self.settings['new_player_protection'] = new_player_protection_days * 86400
                self.settings['post_bounty_protection'] = post_death_protection_days * 86400
                self.settings['pvp_opt_in_cooldown'] = pvp_opt_in_days * 86400
                self.settings['pvp_opt_out_cooldown'] = pvp_opt_out_days * 86400
                self.settings['bounty_opt_in_cooldown'] = bounty_opt_in_days * 86400
                self.settings['bounty_opt_out_cooldown'] = bounty_opt_out_days * 86400
                self.settings['min_bounty_amount'] = min_bounty

                old_force_pvp = self.settings['force_pvp_enabled']
                self.settings['force_pvp_enabled'] = force_pvp

                self.save_config()

                p.send_message(ColorFormat.GREEN + "General settings updated!")
                p.send_message(f"{ColorFormat.YELLOW}PvP Opt-In/Out: {ColorFormat.RESET}{pvp_opt_in_days}d / {pvp_opt_out_days}d")
                p.send_message(f"{ColorFormat.YELLOW}Bounty Opt-In/Out: {ColorFormat.RESET}{bounty_opt_in_days}d / {bounty_opt_out_days}d")
                p.send_message(ColorFormat.GRAY + "Use /bounty config again for waiver costs.")

                if force_pvp != old_force_pvp:
                    if force_pvp:
                        self.server.broadcast_message(
                            ColorFormat.RED + ColorFormat.BOLD +
                            "⚔ FORCE PVP ENABLED! All players can now attack each other! ⚔"
                        )
                    else:
                        self.server.broadcast_message(
                            ColorFormat.GREEN +
                            "Force PvP has been disabled. Players must opt-in to PvP again."
                        )

                # Show waiver costs form
                self.show_config_form_page2(p)

            except (ValueError, TypeError) as e:
                p.send_message(ColorFormat.RED + f"Invalid input! Error: {e}")

        form.on_submit = on_submit
        player.send_form(form)

    def show_config_form_page2(self, player: Player) -> None:
        """Show configuration form for admins - Page 2 (Waiver Costs)"""
        form = ModalForm(
            title="Bounty System Config - Waiver Costs",
            controls=[
                TextInput(
                    label="New Player Waiver Cost",
                    placeholder="1000",
                    default_value=str(self.settings['new_player_waiver_cost'])
                ),
                TextInput(
                    label="Death Protection Waiver Cost",
                    placeholder="500",
                    default_value=str(self.settings['death_protection_waiver_cost'])
                ),
                TextInput(
                    label="PvP Opt-In Waiver Cost",
                    placeholder="1000",
                    default_value=str(self.settings['opt_in_waiver_cost'])
                ),
                TextInput(
                    label="PvP Opt-Out Waiver Cost",
                    placeholder="500",
                    default_value=str(self.settings['opt_out_waiver_cost'])
                ),
                TextInput(
                    label="Bounty Opt-In Waiver Cost",
                    placeholder="1000",
                    default_value=str(self.settings['bounty_opt_in_waiver_cost'])
                ),
                TextInput(
                    label="Bounty Opt-Out Waiver Cost",
                    placeholder="500",
                    default_value=str(self.settings['bounty_opt_out_waiver_cost'])
                )
            ]
        )

        def on_submit(p: Player, data):
            try:
                if isinstance(data, str):
                    import json
                    values = json.loads(data)
                elif isinstance(data, (list, tuple)):
                    values = data
                else:
                    values = list(data)

                new_player_cost = int(values[0]) if values[0] and str(values[0]).strip() else 1000
                death_cost = int(values[1]) if values[1] and str(values[1]).strip() else 500
                pvp_opt_in_cost = int(values[2]) if values[2] and str(values[2]).strip() else 1000
                pvp_opt_out_cost = int(values[3]) if values[3] and str(values[3]).strip() else 500
                bounty_opt_in_cost = int(values[4]) if values[4] and str(values[4]).strip() else 1000
                bounty_opt_out_cost = int(values[5]) if values[5] and str(values[5]).strip() else 500

                if (new_player_cost < 0 or death_cost < 0 or
                    pvp_opt_in_cost < 0 or pvp_opt_out_cost < 0 or
                    bounty_opt_in_cost < 0 or bounty_opt_out_cost < 0):
                    p.send_message(ColorFormat.RED + "All values must be positive!")
                    return

                self.settings['new_player_waiver_cost'] = new_player_cost
                self.settings['death_protection_waiver_cost'] = death_cost
                self.settings['opt_in_waiver_cost'] = pvp_opt_in_cost
                self.settings['opt_out_waiver_cost'] = pvp_opt_out_cost
                self.settings['bounty_opt_in_waiver_cost'] = bounty_opt_in_cost
                self.settings['bounty_opt_out_waiver_cost'] = bounty_opt_out_cost

                self.save_config()

                p.send_message(ColorFormat.GREEN + "Waiver costs updated!")
                p.send_message(f"{ColorFormat.YELLOW}New Player Waiver: {ColorFormat.RESET}{new_player_cost}")
                p.send_message(f"{ColorFormat.YELLOW}Death Protection Waiver: {ColorFormat.RESET}{death_cost}")
                p.send_message(f"{ColorFormat.YELLOW}PvP Opt-In/Out Waiver: {ColorFormat.RESET}{pvp_opt_in_cost} / {pvp_opt_out_cost}")
                p.send_message(f"{ColorFormat.YELLOW}Bounty Opt-In/Out Waiver: {ColorFormat.RESET}{bounty_opt_in_cost} / {bounty_opt_out_cost}")

            except (ValueError, TypeError) as e:
                p.send_message(ColorFormat.RED + f"Invalid input! Error: {e}")

        form.on_submit = on_submit
        player.send_form(form)

    def show_safezone_menu(self, player: Player) -> None:
        """Show the main safezone management menu"""
        form = ActionForm(
            title="Safe Zone Management",
            content="Manage safe zones on the server",
            buttons=[
                Button(text="Create New Zone"),
                Button(text="Remove Zone"),
                Button(text="List All Zones")
            ]
        )

        def on_submit(p: Player, selection: int):
            if selection == 0:
                self.show_create_safezone_form(p)
            elif selection == 1:
                self.show_remove_safezone_form(p)
            elif selection == 2:
                self.show_safezone_list(p)

        form.on_submit = on_submit
        player.send_form(form)

    def show_create_safezone_form(self, player: Player) -> None:
        """Show form to create a new safe zone"""
        # Get player's current position for convenience
        pos = player.location
        x, y, z = int(pos.x), int(pos.y), int(pos.z)

        form = ModalForm(
            title="Create Safe Zone",
            controls=[
                TextInput(
                    label="Zone Name",
                    placeholder="e.g., spawn, arena, shop",
                    default_value=""
                ),
                TextInput(
                    label="Corner 1 - X",
                    placeholder="X coordinate",
                    default_value=str(x - 50)
                ),
                TextInput(
                    label="Corner 1 - Y",
                    placeholder="Y coordinate",
                    default_value=str(y - 10)
                ),
                TextInput(
                    label="Corner 1 - Z",
                    placeholder="Z coordinate",
                    default_value=str(z - 50)
                ),
                TextInput(
                    label="Corner 2 - X",
                    placeholder="X coordinate",
                    default_value=str(x + 50)
                ),
                TextInput(
                    label="Corner 2 - Y",
                    placeholder="Y coordinate",
                    default_value=str(y + 10)
                ),
                TextInput(
                    label="Corner 2 - Z",
                    placeholder="Z coordinate",
                    default_value=str(z + 50)
                ),
                Dropdown(
                    label="Zone Type",
                    options=["No PvP", "PvP Allowed (No Bounties)"],
                    default_index=0
                )
            ],
            submit_button="Create Zone"
        )

        def on_submit(p: Player, json_str: str):
            try:
                data = json.loads(json_str)
                name = data[0].strip()

                if not name:
                    p.send_message(ColorFormat.RED + "Zone name cannot be empty!")
                    return

                # Parse coordinates
                try:
                    x1 = int(data[1])
                    y1 = int(data[2])
                    z1 = int(data[3])
                    x2 = int(data[4])
                    y2 = int(data[5])
                    z2 = int(data[6])
                except ValueError:
                    p.send_message(ColorFormat.RED + "Invalid coordinates! Please enter integers only.")
                    return

                zone_type_index = data[7]
                allow_pvp = zone_type_index == 1

                # Check if zone already exists
                for zone in self.safe_zones:
                    if zone["name"].lower() == name.lower():
                        p.send_message(ColorFormat.RED + f"Safe zone '{name}' already exists!")
                        return

                # Create safe zone
                safe_zone = {
                    "name": name,
                    "x1": min(x1, x2),
                    "y1": min(y1, y2),
                    "z1": min(z1, z2),
                    "x2": max(x1, x2),
                    "y2": max(y1, y2),
                    "z2": max(z1, z2),
                    "dimension": p.dimension.name,
                    "allow_pvp": allow_pvp
                }

                self.safe_zones.append(safe_zone)
                self.save_data()

                zone_type_str = "PvP Allowed (No Bounties)" if allow_pvp else "No PvP"
                p.send_message(ColorFormat.GREEN + f"Safe zone '{name}' created successfully!")
                p.send_message(ColorFormat.YELLOW + f"Type: {zone_type_str}")
                p.send_message(ColorFormat.YELLOW + f"From ({x1}, {y1}, {z1}) to ({x2}, {y2}, {z2})")

            except Exception as e:
                p.send_message(ColorFormat.RED + f"Error creating safe zone: {e}")
                self.logger.error(f"Error in create safezone form: {e}")

        form.on_submit = on_submit
        player.send_form(form)

    def show_remove_safezone_form(self, player: Player) -> None:
        """Show form to remove a safe zone"""
        if len(self.safe_zones) == 0:
            player.send_message(ColorFormat.YELLOW + "No safe zones to remove.")
            return

        zone_names = [zone["name"] for zone in self.safe_zones]

        form = ModalForm(
            title="Remove Safe Zone",
            controls=[
                Dropdown(
                    label="Select Zone to Remove",
                    options=zone_names,
                    default_index=0
                )
            ],
            submit_button="Remove Zone"
        )

        def on_submit(p: Player, json_str: str):
            try:
                data = json.loads(json_str)
                zone_index = data[0]

                if 0 <= zone_index < len(self.safe_zones):
                    zone_name = self.safe_zones[zone_index]["name"]
                    del self.safe_zones[zone_index]
                    self.save_data()
                    p.send_message(ColorFormat.GREEN + f"Safe zone '{zone_name}' removed successfully!")
                else:
                    p.send_message(ColorFormat.RED + "Invalid zone selection!")

            except Exception as e:
                p.send_message(ColorFormat.RED + f"Error removing safe zone: {e}")
                self.logger.error(f"Error in remove safezone form: {e}")

        form.on_submit = on_submit
        player.send_form(form)

    def show_safezone_list(self, player: Player) -> None:
        """Show list of all safe zones"""
        if len(self.safe_zones) == 0:
            player.send_message(ColorFormat.YELLOW + "No safe zones configured.")
            return

        player.send_message(ColorFormat.GREEN + "=== Safe Zones ===")
        for zone in self.safe_zones:
            zone_type = "PvP Allowed (No Bounties)" if zone["allow_pvp"] else "No PvP"
            player.send_message(
                ColorFormat.YELLOW + f"{zone['name']}: " +
                f"({zone['x1']}, {zone['y1']}, {zone['z1']}) to " +
                f"({zone['x2']}, {zone['y2']}, {zone['z2']}) - {zone_type}"
            )

    @event_handler
    def on_player_join(self, event: PlayerJoinEvent) -> None:
        """Track first join time for new player protection"""
        player_name = event.player.name
        is_new = player_name not in self.player_data

        # Ensure player data exists (handles both new and existing players)
        self.ensure_player_data(player_name)

        if is_new:
            self.save_data()
            # Notify about new player protection
            days = self.settings['new_player_protection'] // 86400
            event.player.send_message(
                ColorFormat.GREEN + f"Welcome! You have {days} days of bounty protection as a new player."
            )
            event.player.send_message(
                ColorFormat.YELLOW + "Use /bounty opt to opt into PvP, then /bounty bopt for Bounties."
            )

    @event_handler
    def on_player_death(self, event: PlayerDeathEvent) -> None:
        """Handle bounty claims on player death"""
        victim = event.player
        victim_name = victim.name

        # Check if victim has a bounty
        if victim_name not in self.bounties:
            return

        # Get killer from damage source
        damage_source = event.damage_source
        killer = damage_source.damaging_actor if damage_source else None

        if not isinstance(killer, Player):
            return

        killer_name = killer.name

        # Can't claim your own bounty
        if killer_name == victim_name:
            return

        # Always check Bounty opt-in status for bounty claims (even with force PvP enabled)
        # Force PvP allows everyone to attack, but only bounty-opted-in players can claim/have bounties
        self.ensure_player_data(killer_name)
        self.ensure_player_data(victim_name)

        # Check if killer has Bounty enabled
        if not self.player_data[killer_name].get("bounty_enabled", False):
            # If force PvP is enabled, allow the kill but don't reward the bounty
            if self.settings['force_pvp_enabled']:
                return  # Silently don't award bounty
            else:
                killer.send_message(ColorFormat.RED + "You must have Bounties enabled to claim bounties!")
                killer.send_message(ColorFormat.YELLOW + "Use /bounty bopt to opt into Bounties.")
                return

        # Check if victim has Bounty enabled
        if not self.player_data[victim_name].get("bounty_enabled", False):
            # If force PvP is enabled, allow the kill but don't reward the bounty
            if self.settings['force_pvp_enabled']:
                return  # Silently don't award bounty
            else:
                killer.send_message(ColorFormat.RED + "Target doesn't have Bounties enabled!")
                return

        # Check if killer is in a safe zone
        killer_loc = killer.location
        in_safe_zone, zone_info = self.is_in_safe_zone(
            killer_loc.x, killer_loc.y, killer_loc.z, killer.dimension.name
        )

        if in_safe_zone:
            if not zone_info["allow_pvp"]:
                # No PvP allowed at all
                return
            else:
                # PvP allowed but no bounty claims
                killer.send_message(ColorFormat.YELLOW + "Bounties cannot be claimed in this area!")
                return

        # Check new player protection
        victim_info = self.player_data[victim_name]
        first_join = victim_info["first_join"]
        protection_period = self.settings['new_player_protection']

        if time.time() - first_join < protection_period:
            remaining = int(protection_period - (time.time() - first_join))
            days = remaining // 86400
            hours = (remaining % 86400) // 3600
            killer.send_message(
                ColorFormat.YELLOW + f"{victim_name} has new player protection for {days}d {hours}h more!"
            )
            return

        # Claim bounty
        bounty_data = self.bounties[victim_name]
        total_bounty = bounty_data["total"]

        # Give money to killer
        self.add_money(killer_name, total_bounty)

        # Set post-bounty protection
        victim_info["last_bounty_claimed"] = time.time()

        # Remove bounty
        del self.bounties[victim_name]

        self.save_data()

        # Notifications
        killer.send_message(ColorFormat.GREEN + f"Bounty claimed! +{total_bounty} coins!")
        victim.send_message(ColorFormat.RED + f"Your bounty of {total_bounty} was claimed by {killer_name}!")

        # Broadcast to server
        protection_days = self.settings['post_bounty_protection'] // 86400
        self.server.broadcast_message(
            ColorFormat.GOLD + f"{killer_name} claimed a {total_bounty} coin bounty on {victim_name}!"
        )
        self.server.broadcast_message(
            ColorFormat.YELLOW + f"{victim_name} now has {protection_days} days of bounty protection!"
        )

        # Update death message
        event.death_message = f"{victim_name} was eliminated by {killer_name} (Bounty: {total_bounty})"

    @event_handler
    def on_actor_damage(self, event: ActorDamageEvent) -> None:
        """Prevent PvP damage in safe zones and for players with PvP disabled"""
        # Check if the damaged actor is a player
        victim = event.actor
        if not isinstance(victim, Player):
            return

        # Get damage source
        damage_source = event.damage_source
        if not damage_source:
            return

        victim_name = victim.name
        attacker = None
        attacker_name = None

        # Check if damage is from another player (direct attack)
        if damage_source.damaging_actor and isinstance(damage_source.damaging_actor, Player):
            attacker = damage_source.damaging_actor
            attacker_name = attacker.name

            # Track this attack for fire damage attribution (fire damage comes 1-2 ticks later)
            self.recent_attacks[victim_name] = {
                "attacker_name": attacker_name,
                "timestamp": time.time()
            }

        # Check if damage is from a projectile (arrow, etc.) shot by a player
        # For projectiles: actor = the player who shot it, damaging_actor = the projectile itself
        elif damage_source.is_indirect and damage_source.actor and isinstance(damage_source.actor, Player):
            attacker = damage_source.actor
            attacker_name = attacker.name

            # Track this attack for fire damage attribution
            self.recent_attacks[victim_name] = {
                "attacker_name": attacker_name,
                "timestamp": time.time()
            }

        # Check if this is fire damage from a recent player attack (fire aspect, etc.)
        elif victim_name in self.recent_attacks:
            recent_attack = self.recent_attacks[victim_name]
            # Fire damage typically comes within 5 seconds of the initial hit
            if time.time() - recent_attack["timestamp"] < 5.0:
                attacker_name = recent_attack["attacker_name"]
                # Try to get the attacker player object
                attacker = self.server.get_player(attacker_name)
                if not attacker:
                    # Attacker is offline, but we still prevent the damage
                    event.is_cancelled = True
                    return
            else:
                # Attack is too old, clean it up
                del self.recent_attacks[victim_name]
                return
        else:
            # Not player-caused damage
            return

        # Don't prevent self-damage
        if attacker_name == victim_name:
            return

        # Operators can always attack anyone (for moderation purposes)
        # Check this EARLY so operators bypass safe zone restrictions entirely
        is_operator = attacker.is_op if attacker else False

        # Check if victim is in a safe zone
        victim_loc = victim.location
        victim_in_safe_zone, victim_zone_info = self.is_in_safe_zone(
            victim_loc.x, victim_loc.y, victim_loc.z, victim.dimension.name
        )

        # If victim is in a no-PvP safe zone, block all PvP (unless attacker is OP or has Owner tag)
        if victim_in_safe_zone and not victim_zone_info["allow_pvp"]:
            # Operators and Owner-tagged players are exempt from safe zone restrictions
            if attacker and (is_operator or self.has_owner_tag(attacker)):
                pass  # OP/Owner can attack anywhere
            else:
                event.is_cancelled = True
                if attacker:
                    self.process_safezone_violation(attacker)
                return

        # Check if attacker is in a safe zone (only if attacker is online)
        attacker_in_pvp_zone = False
        if attacker:
            attacker_loc = attacker.location
            attacker_in_safe_zone, attacker_zone_info = self.is_in_safe_zone(
                attacker_loc.x, attacker_loc.y, attacker_loc.z, attacker.dimension.name
            )
            # Check if attacker is in a no-PvP safe zone
            if attacker_in_safe_zone and not attacker_zone_info["allow_pvp"]:
                # Operators and Owner-tagged players are exempt from safe zone restrictions
                if is_operator or self.has_owner_tag(attacker):
                    pass  # OP/Owner can attack anywhere
                else:
                    event.is_cancelled = True
                    self.process_safezone_violation(attacker)
                    return
            # Track if attacker is in a PvP-allowed zone
            attacker_in_pvp_zone = attacker_in_safe_zone and attacker_zone_info["allow_pvp"]

        # Check if victim is in a PvP-allowed zone (allows PvP but no bounties)
        victim_in_pvp_zone = victim_in_safe_zone and victim_zone_info["allow_pvp"]

        # If both players are in a PvP zone, skip opt-in and protection checks
        # PvP zones force combat regardless of opt-in status
        in_pvp_zone = victim_in_pvp_zone or attacker_in_pvp_zone

        if not is_operator and not in_pvp_zone:
            # If force PvP is enabled, skip PvP opt-in checks (but still check protections below)
            if not self.settings['force_pvp_enabled']:
                # Check if victim has PvP disabled
                if victim_name in self.player_data:
                    if not self.player_data[victim_name].get("pvp_enabled", False):
                        event.is_cancelled = True
                        if attacker:
                            attacker.send_message(ColorFormat.RED + f"{victim_name} has PvP disabled!")
                        return

                # Check if attacker has PvP disabled
                if attacker_name in self.player_data:
                    if not self.player_data[attacker_name].get("pvp_enabled", False):
                        event.is_cancelled = True
                        if attacker:
                            attacker.send_message(ColorFormat.RED + "You must enable PvP to attack other players!")
                        return

        # Operators bypass protection periods (for moderation)
        # Force PvP and PvP zones also bypass protection periods
        if not is_operator and not self.settings['force_pvp_enabled'] and not in_pvp_zone:
            # Check new player protection for victim
            if victim_name in self.player_data:
                victim_info = self.player_data[victim_name]
                first_join = victim_info["first_join"]
                protection_period = self.settings['new_player_protection']

                if time.time() - first_join < protection_period:
                    event.is_cancelled = True
                    remaining = int(protection_period - (time.time() - first_join))
                    days = remaining // 86400
                    hours = (remaining % 86400) // 3600
                    if attacker:
                        attacker.send_message(
                            ColorFormat.YELLOW + f"{victim_name} has new player protection for {days}d {hours}h more!"
                        )
                    return

            # Check post-bounty protection for victim
            if victim_name in self.player_data:
                victim_info = self.player_data[victim_name]
                last_bounty_claimed = victim_info.get("last_bounty_claimed", 0)
                protection_period = self.settings['post_bounty_protection']

                if time.time() - last_bounty_claimed < protection_period:
                    event.is_cancelled = True
                    remaining = int(protection_period - (time.time() - last_bounty_claimed))
                    days = remaining // 86400
                    hours = (remaining % 86400) // 3600
                    if attacker:
                        attacker.send_message(
                            ColorFormat.YELLOW + f"{victim_name} has post-bounty protection for {days}d {hours}h more!"
                        )
                    return

    @event_handler
    def on_player_move(self, event: PlayerMoveEvent) -> None:
        """Check if player enters/exits safe zones (optional notification)"""
        # This can be used for notifications when entering/leaving safe zones
        # For now, we just check zones during bounty claims
        pass

    @event_handler
    def on_player_interact(self, event: PlayerInteractEvent) -> None:
        """Handle PvP altar item interactions"""
        # Check if player has an item first
        if not event.has_item:
            return

        # Get the item
        item = event.item
        if not item:
            return

        # Check if it's the PvP altar item (ninjos:pvp_altar)
        item_type = item.type
        if item_type != "ninjos:pvp_altar":
            return

        # Only trigger on right-click to avoid multiple menu opens
        # Check action after confirming it's the right item
        action = str(event.action)
        if "RIGHT_CLICK" not in action:
            return

        # Cancel the event to prevent normal item use
        event.is_cancelled = True

        # Debounce: prevent multiple menu opens from rapid interactions
        player = event.player
        player_name = player.name
        current_time = time.time()
        
        # Check if player interacted within the last 0.5 seconds
        last_interaction = self.altar_interactions.get(player_name, 0)
        if current_time - last_interaction < 0.5:
            # Skip this interaction - too soon after the last one
            return
        
        # Update last interaction time
        self.altar_interactions[player_name] = current_time

        # Show the PvP altar menu
        self.show_pvp_altar_menu(player)

    def show_pvp_altar_menu(self, player: Player) -> None:
        """Show the PvP altar menu with bounty system options"""
        player_info = self.ensure_player_data(player.name)
        is_pvp_enabled = player_info.get("pvp_enabled", False)
        is_bounty_enabled = player_info.get("bounty_enabled", False)
        current_time = time.time()

        # Check new player status
        first_join = player_info.get("first_join", current_time)
        new_player_protection = self.settings['new_player_protection']
        new_player_remaining = new_player_protection - (current_time - first_join)
        is_new_player = new_player_remaining > 0

        # Build PvP status display
        if is_pvp_enabled:
            pvp_status = f"{ColorFormat.GREEN}✓ OPTED IN{ColorFormat.RESET}"
        else:
            pvp_status = f"{ColorFormat.RED}✗ OPTED OUT{ColorFormat.RESET}"

        # Build Bounty status display
        if is_bounty_enabled:
            bounty_status = f"{ColorFormat.GREEN}✓ OPTED IN{ColorFormat.RESET}"
        else:
            bounty_status = f"{ColorFormat.RED}✗ OPTED OUT{ColorFormat.RESET}"

        # Build content with clear status
        content = f"{ColorFormat.GOLD}Welcome to the PvP Altar!{ColorFormat.RESET}\n\n"
        content += f"PvP Status: {pvp_status}\n"
        content += f"Bounty Status: {bounty_status}\n"

        if not is_pvp_enabled:
            content += f"{ColorFormat.GRAY}You are protected from PvP{ColorFormat.RESET}\n"
        elif not is_bounty_enabled:
            content += f"{ColorFormat.GRAY}PvP enabled, but no bounty participation{ColorFormat.RESET}\n"
        else:
            content += f"{ColorFormat.GRAY}Full bounty hunting enabled{ColorFormat.RESET}\n"

        # Show new player status only if still protected
        if is_new_player:
            days = int(new_player_remaining // 86400)
            hours = int((new_player_remaining % 86400) // 3600)
            content += f"\n{ColorFormat.YELLOW}⚠ New Player Protection:{ColorFormat.RESET}\n"
            content += f"{ColorFormat.GRAY}Protected for {days}d {hours}h more{ColorFormat.RESET}\n"

        content += f"\n{ColorFormat.GOLD}Choose an option:{ColorFormat.RESET}"

        # Build buttons based on status
        buttons = []

        # Only show "Place Bounty" if player has bounty enabled
        if is_bounty_enabled:
            buttons.append(Button(text="Place Bounty"))

        buttons.append(Button(text="Waive Protection/Cooldown"))
        buttons.append(Button(text="Toggle PvP Opt In/Out"))

        # Only show bounty toggle if PvP is enabled
        if is_pvp_enabled:
            buttons.append(Button(text="Toggle Bounty Opt In/Out"))

        buttons.append(Button(text="View Leaderboard"))

        form = ActionForm(
            title="PvP Altar",
            content=content,
            buttons=buttons
        )

        def on_submit(p: Player, selection: int):
            button_index = 0

            # Place Bounty (only if bounty enabled)
            if is_bounty_enabled:
                if selection == button_index:
                    self.show_bounty_form(p)
                    return
                button_index += 1

            # Waive Protection/Cooldown
            if selection == button_index:
                self.show_waive_cooldown_form(p)
                return
            button_index += 1

            # Toggle PvP Opt In/Out
            if selection == button_index:
                self.toggle_pvp_opt(p)
                return
            button_index += 1

            # Toggle Bounty Opt In/Out (only if PvP enabled)
            if is_pvp_enabled:
                if selection == button_index:
                    self.toggle_bounty_opt(p)
                    return
                button_index += 1

            # View Leaderboard
            if selection == button_index:
                self.show_bounty_leaderboard(p)
                return

        form.on_submit = on_submit
        player.send_form(form)

    def is_in_safe_zone(self, x: float, y: float, z: float, dimension: str) -> Tuple[bool, Optional[Dict]]:
        """Check if coordinates are in a safe zone"""
        for zone in self.safe_zones:
            if zone["dimension"] != dimension:
                continue

            if (zone["x1"] <= x <= zone["x2"] and
                zone["y1"] <= y <= zone["y2"] and
                zone["z1"] <= z <= zone["z2"]):
                return True, zone

        return False, None

    def has_owner_tag(self, player: Player) -> bool:
        """Check if player has the 'Owner' scoreboard tag"""
        try:
            return "Owner" in player.scoreboard_tags
        except:
            return False

    def process_safezone_violation(self, attacker: Player) -> None:
        """
        Process a safe zone PvP violation.
        Tracks strikes and kicks player after 3rd violation.
        Strikes decay/reset after a configurable period of no violations.
        """
        attacker_name = attacker.name
        current_time = time.time()
        decay_time = self.settings.get("safezone_strike_decay", 3600)  # Default 1 hour
        
        # Check if player has existing strikes
        if attacker_name in self.safezone_strikes:
            last_strike = self.safezone_strikes[attacker_name].get("last_strike", 0)
            time_since_last = current_time - last_strike
            
            # If enough time has passed, reset strikes
            if time_since_last >= decay_time:
                self.safezone_strikes[attacker_name] = {"count": 0, "last_strike": current_time}
                self.logger.info(f"Strike count for {attacker_name} decayed/reset after {int(time_since_last)}s of no violations")
        else:
            # First violation for this player
            self.safezone_strikes[attacker_name] = {"count": 0, "last_strike": current_time}
        
        # Increment strike count and update timestamp
        self.safezone_strikes[attacker_name]["count"] += 1
        self.safezone_strikes[attacker_name]["last_strike"] = current_time
        strikes = self.safezone_strikes[attacker_name]["count"]
        
        # Calculate time remaining before strikes would decay (for warning message)
        decay_remaining = decay_time
        decay_minutes = int(decay_remaining // 60)
        
        if strikes == 1:
            attacker.send_message(ColorFormat.RED + "⚠ Warning 1/3: PvP is not allowed in safe zones!")
            attacker.send_message(ColorFormat.YELLOW + "Continued violations will result in a kick.")
            attacker.send_message(ColorFormat.GRAY + f"(Strikes reset after {decay_minutes} minutes of no violations)")
        elif strikes == 2:
            attacker.send_message(ColorFormat.RED + "⚠ Warning 2/3: One more violation will result in a KICK!")
            attacker.send_message(ColorFormat.GRAY + f"(Strikes reset after {decay_minutes} minutes of no violations)")
        else:
            # 3rd strike - kick the player
            self.logger.warning(f"Kicking {attacker_name} for safe zone PvP violations (3 strikes)")
            # Reset strikes before kick
            del self.safezone_strikes[attacker_name]
            # Kick the player
            self.server.dispatch_command(
                self.server.command_sender,
                f'kick "{attacker_name}" Kicked for attacking in safe zones (3 violations)'
            )

    def get_money(self, player: Player) -> int:
        """Get player's current money from scoreboard"""
        try:
            scoreboard = self.server.scoreboard
            objective = scoreboard.get_objective(self.settings['money_objective'])

            if not objective:
                self.logger.error(f"Scoreboard objective '{self.settings['money_objective']}' not found!")
                return 0

            score = objective.get_score(player)
            if not score:
                self.logger.warning(f"No score found for player '{player.name}' in objective '{self.settings['money_objective']}'")
                return 0

            # Check if score is actually set
            if not score.is_score_set:
                self.logger.warning(f"Score not set for player '{player.name}' in objective '{self.settings['money_objective']}'")
                return 0

            return score.value
        except Exception as e:
            self.logger.error(f"Error getting money for {player.name}: {e}")
            return 0

    def has_money(self, player: Player, amount: int) -> bool:
        """Check if player has enough money in scoreboard"""
        current_money = self.get_money(player)
        return current_money >= amount

    def add_money(self, player_name: str, amount: int) -> bool:
        """Add money to player's scoreboard"""
        try:
            # Execute command as server (console)
            command = f"scoreboard players add \"{player_name}\" {self.settings['money_objective']} {amount}"
            self.server.dispatch_command(self.server.command_sender, command)
            return True
        except Exception as e:
            self.logger.error(f"Failed to add money: {e}")
            return False

    def remove_money(self, player_name: str, amount: int) -> bool:
        """Remove money from player's scoreboard"""
        try:
            # Execute command as server (console)
            command = f"scoreboard players remove \"{player_name}\" {self.settings['money_objective']} {amount}"
            self.server.dispatch_command(self.server.command_sender, command)
            return True
        except Exception as e:
            self.logger.error(f"Failed to remove money: {e}")
            return False

    def deduct_money(self, player: Player, amount: int) -> bool:
        """Deduct money from player (wrapper for remove_money)"""
        return self.remove_money(player.name, amount)