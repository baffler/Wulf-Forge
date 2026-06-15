import sys, unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
from network.packets.packet_config import PacketConfig
from core.entity import GameEntity
from core.sim.tank import TankSim
from core.sim.inputs import ACTION_THROTTLE


class PlayerSimTickTests(unittest.TestCase):
    def test_tick_advances_each_player_from_inputs(self):
        ent = GameEntity(net_id=1, unit_type=0, team_id=1, pos=(0.0, 0.0, 10.0))
        ent.actions = {ACTION_THROTTLE: 1.0}
        session = SimpleNamespace(entity=ent, player_id=1, is_logged_in=True)
        server = SimpleNamespace(sessions=[session], tank_sim=TankSim(PacketConfig()))

        start = ent.pos
        for _ in range(20):
            main.player_sim_tick(server, dt=0.1)
        moved = abs(ent.pos[0] - start[0]) + abs(ent.pos[1] - start[1])
        self.assertGreater(moved, 1.0)

    def test_tick_skips_players_without_entity(self):
        server = SimpleNamespace(
            sessions=[SimpleNamespace(entity=None, player_id=2, is_logged_in=True)],
            tank_sim=TankSim(PacketConfig()),
        )
        main.player_sim_tick(server, dt=0.1)  # must not raise


if __name__ == "__main__":
    unittest.main()
