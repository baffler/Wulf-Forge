from network.packets.player import CommMessagePacket

def send_system_message(ctx, message):
    """
    Sends a system/chat message to the client associated with the context.
    """
    # message type 5 for system message
    pkt = CommMessagePacket(
        message_type=5,
        source_player_id=ctx.server.cfg.player.player_id, 
        chat_scope_id=1,
        recepient_id=0, 
        message=message
    )
    ctx.send(pkt)