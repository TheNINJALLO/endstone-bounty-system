# Endstone Bounty System

A comprehensive bounty system plugin for Minecraft Bedrock Edition servers using Endstone. Place bounties on players, manage safe zones, and control PvP with opt-in/opt-out mechanics.

## Features

### Core Bounty System
- **Place Bounties**: Players can place bounties on other players using the vanilla "Money" scoreboard objective
- **Stackable Bounties**: Multiple players can add to the same bounty, increasing the reward
- **Leaderboard**: View all active bounties sorted by total amount
- **Automatic Claiming**: Bounties are automatically claimed when the target is killed by another player
- **User-Friendly Forms**: All interactions use intuitive in-game forms (no complex command syntax required)

### Safe Zones
- **No PvP Zones**: Areas where players cannot be killed at all
- **PvP Without Bounties**: Areas where PvP is allowed but bounties cannot be claimed
- **Multi-Dimensional**: Safe zones are dimension-specific (Overworld, Nether, End)

### PvP Opt-In/Opt-Out System
- **Player Choice**: Players can enable or disable PvP participation
- **Cooldowns**: Customizable cooldowns for toggling PvP status (default: 1 day to opt-in, 3 days to opt-out)
- **Protection**: Players with PvP disabled cannot be bounty targets or place bounties
- **Bounty Restrictions**: Only opted-in players can place bounties on other opted-in players
- **Force PvP Mode**: Optional server-wide setting that allows all players to attack each other while maintaining bounty restrictions for opted-in players only

### Protection Periods
- **New Player Protection**: New players have a configurable protection period before bounties can be claimed on them (default: 3 days)
- **Post-Bounty Protection**: After a bounty is claimed, players get a protection period before new bounties can be placed (default: 3 days)
- **Comprehensive Protection**: All protections apply to direct attacks, projectiles (arrows), and fire damage (fire aspect weapons)

## Installation

1. Install Endstone on your Minecraft Bedrock Dedicated Server
2. Copy the plugin to your `plugins` directory:
   ```bash
   pip install endstone-bounty-system
   ```
3. Ensure you have a scoreboard objective named "Money" created:
   ```
   /scoreboard objectives add Money dummy "Money"
   ```
4. Restart your server

## Commands

### Player Commands

#### `/bounty`
Opens the bounty placement form where you can:
- Select a target player from the dropdown (only shows players with PvP enabled)
- Enter the bounty amount
- Confirm the bounty placement

**Requirements**: You must have PvP enabled to place bounties.

**Permission**: `bounty.use` (default: everyone)

#### `/bounty list`
Displays the bounty leaderboard showing:
- All active bounties
- Total bounty amounts
- List of contributors and their individual contributions

**Permission**: `bounty.use` (default: everyone)

#### `/bounty opt`
Toggle your PvP opt-in/opt-out status.
- Shows your current PvP status
- Displays remaining cooldown time if applicable
- Subject to cooldowns (1 day to opt-in, 3 days to opt-out by default)

**Permission**: `bounty.use` (default: everyone)

#### `/bounty waive`
Opens a form to waive protection periods early by paying a fee:
- **Waive New Player Protection**: Pay to remove new player protection early (default: 1000 coins)
- **Waive Post-Bounty Protection**: Pay to remove post-bounty protection early (default: 500 coins)

**Permission**: `bounty.use` (default: everyone)

### Admin Commands (Operator Only)

#### `/bounty config`
Opens the server configuration form to adjust plugin settings:
- **New Player Protection**: Duration in days (default: 3 days)
- **Post-Bounty Protection**: Duration in days (default: 3 days)
- **PvP Opt-In Cooldown**: Duration in days (default: 1 day)
- **PvP Opt-Out Cooldown**: Duration in days (default: 3 days)
- **New Player Waiver Cost**: Cost to waive new player protection (default: 1000 coins)
- **Death Protection Waiver Cost**: Cost to waive post-bounty protection (default: 500 coins)
- **Minimum Bounty Amount**: Minimum bounty that can be placed (default: 100 coins)
- **Force PvP Enabled**: Toggle Force PvP mode on/off

All settings are saved to `config.json` and persist across server restarts.

**Permission**: `bounty.admin` (default: op)

#### `/safezone`
Opens the Safe Zone Management menu with the following options:

**Permission**: `bounty.admin` (default: op)

##### Create New Zone
Opens a form to create a new safe zone:
- **Zone Name**: Unique identifier for the zone (e.g., spawn, arena, shop)
- **Corner 1 Coordinates**: X, Y, Z coordinates for the first corner
- **Corner 2 Coordinates**: X, Y, Z coordinates for the opposite corner
- **Zone Type**: Choose between:
  - `No PvP`: Players cannot be killed in this zone at all
  - `PvP Allowed (No Bounties)`: PvP is allowed but bounties cannot be claimed

The form automatically shows your current position for convenience when setting coordinates.

##### Remove Zone
Opens a dropdown menu to select and remove an existing safe zone.

##### List All Zones
Displays all configured safe zones with their:
- Name
- Coordinates (both corners)
- Zone type (No PvP or PvP Allowed)
- Dimension

## Configuration

The plugin creates a `config.json` file in the `plugins/endstone_bounty_system` directory with the following customizable settings:

```json
{
    "pvp_opt_in_cooldown": 86400,
    "pvp_opt_out_cooldown": 259200,
    "new_player_protection": 259200,
    "post_bounty_protection": 259200,
    "new_player_waiver_cost": 1000,
    "death_protection_waiver_cost": 500,
    "min_bounty_amount": 100,
    "money_objective": "Money",
    "force_pvp_enabled": false
}
```

### Configuration Options

| Option | Default | Description |
|--------|---------|-------------|
| `pvp_opt_in_cooldown` | 86400 | Cooldown in seconds for enabling PvP (1 day) |
| `pvp_opt_out_cooldown` | 259200 | Cooldown in seconds for disabling PvP (3 days) |
| `new_player_protection` | 259200 | Protection period for new players in seconds (3 days) |
| `post_bounty_protection` | 259200 | Protection period after bounty is claimed in seconds (3 days) |
| `new_player_waiver_cost` | 1000 | Cost to waive new player protection early |
| `death_protection_waiver_cost` | 500 | Cost to waive post-bounty protection early |
| `min_bounty_amount` | 100 | Minimum bounty amount that can be placed |
| `money_objective` | "Money" | Name of the scoreboard objective used for currency |
| `force_pvp_enabled` | false | If true, all players can attack each other (safe zones still apply), but only opted-in players can claim/have bounties |

## How It Works

### Placing a Bounty

1. **Enable PvP first**: You must have PvP enabled to place bounties (`/bounty opt`)
2. Use `/bounty` to open the bounty form
3. Select the target player from the dropdown (only shows players with PvP enabled)
4. Enter the bounty amount (must have enough money in your scoreboard)
5. Confirm to place the bounty
6. The money is immediately deducted from your scoreboard
7. The target is notified of the bounty

**Note**: Only players with PvP enabled can place bounties on other players with PvP enabled.

### Claiming a Bounty

Bounties are automatically claimed when:
1. The bounty target is killed by another player
2. Both the killer and target have PvP enabled
3. Neither player is in a safe zone (or in a bounty-restricted zone)
4. The target is not under new player or post-bounty protection

When claimed:
- The full bounty amount is added to the killer's scoreboard
- The bounty is removed from the target
- The target receives a 3-day (default) protection period
- A server-wide broadcast announces the bounty claim

### Safe Zones

Safe zones are rectangular areas defined by two opposite corners. They can be configured in two modes:

1. **No PvP** (`no_pvp`): Players cannot be killed at all in this zone
2. **PvP Without Bounties** (`pvp_no_bounty`): PvP is allowed, but bounty claims are prevented

### PvP Opt-In/Opt-Out

Players can control their participation in the bounty system:
- New players start with PvP **disabled**
- Use `/bounty opt` to toggle PvP status
- Cooldowns prevent rapid toggling to avoid exploitation:
  - **Opt-in cooldown**: 1 day (default)
  - **Opt-out cooldown**: 3 days (default)
- Players with PvP disabled cannot:
  - Have bounties placed on them
  - Place bounties on others
  - Claim bounties on others
  - Attack other players (unless Force PvP mode is enabled)

### Force PvP Mode

When Force PvP mode is enabled by an administrator:
- **All players can attack each other**, regardless of opt-in status
- **Safe zones are still respected** (no PvP in no-PvP zones)
- **New player and post-bounty protections are bypassed**
- **Only opted-in players can claim bounties** (non-opted-in players get nothing)
- **Only opted-in players can have bounties placed on them**
- This mode is useful for PvP events or servers that want open combat with optional bounty participation

### Protection Periods

#### New Player Protection
- Starts when a player first joins the server
- Default: 3 days (259,200 seconds)
- Bounties can be placed, but cannot be claimed during this period
- Players are notified of remaining protection time

#### Post-Bounty Protection
- Starts immediately after a bounty is claimed on a player
- Default: 3 days (259,200 seconds)
- New bounties cannot be placed on the player during this period
- Prevents immediate re-bounty griefing

#### Protection Against All Damage Types
The plugin protects players from all forms of player-caused damage:
- **Direct melee attacks** (swords, axes, etc.)
- **Projectiles** (arrows, tridents, etc.)
- **Fire damage** from fire aspect weapons
- Fire damage is tracked and attributed to the player who caused it (up to 5 seconds after the initial hit)

## Data Storage

The plugin stores data in JSON files in the `plugins/endstone_bounty_system` directory:

- `config.json`: Configuration settings
- `bounty_data.json`: Active bounties, safe zones, and player data

All data is automatically saved when:
- The plugin is disabled/reloaded
- Changes are made to bounties or safe zones
- Player data is updated

## Permissions

| Permission | Default | Description |
|------------|---------|-------------|
| `bounty.use` | true | Allows using player bounty commands |
| `bounty.admin` | op | Allows managing safe zones |

## Technical Details

### Server-Side Scoreboard Operations

The plugin uses server-executed commands to manage the Money scoreboard, ensuring:
- All operations are performed as the console/server, not as the player
- Player-specific scoreboards are correctly accessed
- No permission issues with scoreboard modifications

Example internal commands:
```
scoreboard players add "PlayerName" Money 1000
scoreboard players remove "PlayerName" Money 500
```

### Event Handling

The plugin listens for:
- `PlayerJoinEvent`: Track new player join times and initialize player data
- `PlayerDeathEvent`: Handle bounty claims when players are killed
- `ActorDamageEvent`: Prevent unauthorized PvP damage (direct attacks, projectiles, and fire damage)
- `PlayerMoveEvent`: Optional zone entry/exit notifications

## Requirements

- Endstone 0.5+
- Python 3.9+
- Minecraft Bedrock Dedicated Server
- A scoreboard objective named "Money" (or configured name)

## Troubleshooting

### "Money objective not found" error
Create the scoreboard objective:
```
/scoreboard objectives add Money dummy "Money"
```

### Bounties not being claimed
Check that:
1. Both players have PvP enabled (`/bounty opt`)
2. Neither player is in a safe zone
3. The target is not under protection (new player or post-bounty protection)
4. The killer actually delivered the final blow
5. If Force PvP mode is enabled, verify both players are opted-in to claim/have bounties

### Cannot place bounties
Check that:
1. You have PvP enabled (`/bounty opt`)
2. The target player has PvP enabled
3. You have enough money in your scoreboard
4. The target is not under post-bounty protection

### Safe zones not working
Verify:
1. Coordinates are correct (use F3 in-game)
2. The dimension name matches
3. The zone was created successfully (check `/safezone list`)

## Support & Issues

For bug reports, feature requests, or support, please contact the server administrator.

## License

Apache-2.0

## Credits

Created for Endstone Minecraft Bedrock servers.