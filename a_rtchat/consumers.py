from channels.generic.websocket import AsyncWebsocketConsumer
from .models import *
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
import json
from asgiref.sync import sync_to_async

class ChatroomConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope['user']
        self.chatroom_name = self.scope['url_route']['kwargs']['chatroom_name']
        self.chatroom = await self.get_chatroom(self.chatroom_name)
        # Use a set to track messages sent *to this specific consumer instance*
        self.sent_message_ids_to_client = set()

        if not self.chatroom:
            print(f"[CONNECT] Chatroom '{self.chatroom_name}' not found.")
            await self.close()
            return

        await self.channel_layer.group_add(
            self.chatroom_name, self.channel_name
        )

        print(f"[CONNECT] {self.user} joined chatroom '{self.chatroom_name}'")

        # Add and update online users
        is_newly_online = False
        if self.user not in await self.get_online_users():
            await self.add_online_user(self.user)
            is_newly_online = True
            print(f"[ONLINE] {self.user} marked as online in {self.chatroom_name}")
            # Only update count if the user was newly marked online
            await self.update_online_count()

        await self.accept()

        # Mark unread messages as read when connecting
        unread_messages = await self.get_unread_messages()
        if unread_messages:
            print(f"[UNREAD] {len(unread_messages)} unread messages found on connect for {self.user}")
            for message in unread_messages:
                await self.mark_message_as_read(message.id)
                # Send a status update for messages marked as read on connect
                # This ensures other users see the 'read' status if they are online
                await self.channel_layer.group_send(
                    self.chatroom_name,
                    {
                        "type": "chat_message_status",
                        "message_id": message.id,
                        "status": "read",
                    }
                )

    async def disconnect(self, close_code):
        if self.chatroom and self.user:
            await self.channel_layer.group_discard(
                self.chatroom_name, self.channel_name
            )

            print(f"[DISCONNECT] {self.user} left chatroom '{self.chatroom_name}'")

            # Remove user from online list and update count
            if self.user in await self.get_online_users():
                await self.remove_online_user(self.user)
                print(f"[OFFLINE] {self.user} removed from online list in {self.chatroom_name}")
                await self.update_online_count()

    async def receive(self, text_data):
        text_data_json = json.loads(text_data)
        print(f"[RECEIVE] Data from {self.user}: {text_data_json}")

        if 'body' in text_data_json:
            body = text_data_json['body']
            if not body or not body.strip():
                return # Don't create empty messages

            message = await self.create_message(body)
            if message:
                print(f"[NEW MESSAGE] Message {message.id} created by {self.user}")

                # Send message to group for rendering and delivery marking by recipients
                await self.channel_layer.group_send(
                    self.chatroom_name,
                    {
                        'type': 'message_handler',
                        'message_id': message.id,
                    }
                )

        elif 'read_message_id' in text_data_json:
            message_id = text_data_json['read_message_id']
            print(f"[READ MESSAGE] User {self.user} attempting to mark message {message_id} as read")
            await self.mark_message_as_read(message_id)

    async def message_handler(self, event):
        message_id = event['message_id']

        # Avoid processing the same message ID multiple times within this consumer instance
        if message_id in self.sent_message_ids_to_client:
            print(f"[MESSAGE HANDLER] Skipping already processed message ID for client: {message_id}")
            return

        message = await self.get_message(message_id)
        if not message:
             print(f"[MESSAGE HANDLER] Message with ID {message_id} not found.")
             return

        message_author = await sync_to_async(lambda: message.author)()

        # Mark as delivered if the recipient is the current user and not the author,
        # and this is the first time we are sending it to this client.
        if self.user != message_author:
             # Mark as delivered right before sending to this client's channel
             if not await self.is_message_delivered_to_user(message, self.user):
                await self.add_message_to_delivered(message, self.user)
                print(f"[DELIVERED] Message {message_id} marked delivered for {self.user}")

        # Determine status (read/delivered/sent) based on current state
        # We re-calculate status here to get the most up-to-date info for rendering
        status = await self.get_message_status(message)

        # Render the message HTML
        context = {
            'message': message,
            'user': self.user,
            'chat_group': self.chatroom,
            'status': status,
            'chatroom_name': self.chatroom_name,
        }
        html = await sync_to_async(render_to_string)("a_rtchat/partials/chat_message_p.html", context)

        # Send the rendered message HTML to the client
        await self.send(text_data=json.dumps({
            'type': 'chat_message',
            'html': html,
            'message_id': message_id,
        }))

        # Add message ID to the set of processed messages for this consumer instance
        self.sent_message_ids_to_client.add(message_id)

    async def chat_message_status(self, event):
        message_id = event['message_id']
        status = event['status']

        message = await self.get_message(message_id)
        if not message:
            print(f"[CHAT MESSAGE STATUS] Message with ID {message_id} not found.")
            return

        # Render the message again with the updated status and send to the client
        context = {
            'message': message,
            'user': self.user,
            'chat_group': self.chatroom,
            'status': status,
            'chatroom_name': self.chatroom_name,
        }
        html = await sync_to_async(render_to_string)("a_rtchat/partials/chat_message_p.html", context)

        # Send the updated status HTML to the client
        await self.send(text_data=json.dumps({
            'type': 'chat_message_status',
            'html': html,
            'message_id': message_id,
            'status': status,
        }))

    async def update_online_count(self):
        if not self.chatroom:
            return
        # Get all online users except the current user for the count displayed to others
        online_users = await self.get_online_users()
        # The count should reflect others online in the room
        online_count = len([u for u in online_users if u != self.user])
        print(f"[ONLINE COUNT] {online_count} users online (excluding current) in {self.chatroom_name}")

        # Send the updated count to the group
        await self.channel_layer.group_send(
            self.chatroom_name,
            {
                'type': 'online_count_handler',
                'online_count': online_count
            }
        )

    async def online_count_handler(self, event):
        online_count = event['online_count']
        print(f"[ONLINE COUNT HANDLER] Sending updated count: {online_count}")

        # Prepare context for rendering the online count partial
        # We need the chat_group to check online members in the template partial
        context = {
            'online_count': online_count,
            'chat_group': self.chatroom, # Pass chat_group to the template
            'user': self.user, # Pass current user for online status dot in template
        }

        # Render the online count partial
        html = await sync_to_async(render_to_string)("a_rtchat/partials/online_count.html", context)

        # Send the updated online count HTML to the client
        await self.send(text_data=json.dumps({
             'type': 'online_count',
             'html': html,
        }))

    # Helper methods for async database operations
    async def get_chatroom(self, chatroom_name):
        if not chatroom_name:
            return None
        # Use async first() to get a single object or None
        return await ChatGroup.objects.filter(group_name=chatroom_name).afirst()

    async def get_online_users(self):
        # Ensure we are fetching the related online users for this specific chatroom
        if not self.chatroom:
            return []
        # Use async all() and convert to list
        return await sync_to_async(list)(self.chatroom.user_online.all())

    async def add_online_user(self, user):
         if self.chatroom and user:
            # Use async add()
            await sync_to_async(self.chatroom.user_online.add)(user)

    async def remove_online_user(self, user):
        if self.chatroom and user:
            # Use async remove()
            await sync_to_async(self.chatroom.user_online.remove)(user)

    async def get_unread_messages(self):
       # Fetch messages for this chatroom not read by the current user and not sent by the current user.
       if not self.chatroom or not self.user:
           return []
       # Use async filter and exclude, then all() and convert to list
       return await sync_to_async(list)(
           self.chatroom.chat_message.filter(group=self.chatroom).exclude(read_by=self.user).exclude(author=self.user).all()
       )

    async def create_message(self, body):
        if not self.user or not self.chatroom or not body or not body.strip():
            return None
        # Use async create
        message = await GroupMessage.objects.acreate(body=body.strip(), author=self.user, group=self.chatroom)
        return message

    async def get_message(self, message_id):
        if not message_id or not self.chatroom:
            return None
        # Ensure the message belongs to the current chatroom and use async first()
        return await GroupMessage.objects.filter(id=message_id, group=self.chatroom).afirst()

    async def is_message_delivered_to_user(self, message, user):
        if not message or not user:
            return False
        # Use async filter and aexists()
        return await message.delivered_to.filter(id=user.id).aexists()

    async def add_message_to_delivered(self, message, user):
        if message and user:
            # Use async add()
            await sync_to_async(message.delivered_to.add)(user)

    async def get_group_members_excluding_author(self, message):
        if not message:
            return []
        group = await sync_to_async(lambda: message.group)()
        if not group:
            return []
        author = await sync_to_async(lambda: message.author)()
        if not author:
             return await sync_to_async(list)(group.members.all())
        # Use async exclude and all() and convert to list
        return await sync_to_async(list)(group.members.exclude(id=author.id).all())

    async def get_read_by_count(self, message):
        if not message:
            return 0
        author = await sync_to_async(lambda: message.author)()
        if not author:
            # If author is missing, count all users who read it
             return await sync_to_async(lambda: message.read_by.count())()
        # Use async exclude and count()
        return await sync_to_async(lambda: message.read_by.exclude(id=author.id).count())()

    async def get_delivered_to_count(self, message):
        if not message:
            return 0
        author = await sync_to_async(lambda: message.author)()
        if not author:
             # If author is missing, count all users it was delivered to
             return await sync_to_async(lambda: message.delivered_to.count())()
        # Use async exclude and count()
        return await sync_to_async(lambda: message.delivered_to.exclude(id=author.id).count())()

    async def get_message_read_by(self, message):
         if not message:
             return []
         # Use async all() and convert to list
         return await sync_to_async(list)(message.read_by.all())

    async def add_message_to_read_by(self, message, user):
        if message and user:
            # Use async add()
            await sync_to_async(message.read_by.add)(user)

    async def get_group_members(self, message):
        if not message:
            return []
        group = await sync_to_async(lambda: message.group)()
        if not group:
            return []
        # Use async all() and convert to list
        return await sync_to_async(list)(group.members.all())

    async def get_message_status(self, message):
        group_members = await self.get_group_members_excluding_author(message)
        read_by_count = await self.get_read_by_count(message)
        delivered_to_count = await self.get_delivered_to_count(message)
        total_members = len(group_members)
        read_by_users = await self.get_message_read_by(message)
        print(f"[DEBUG] read_by users: {[u.username for u in read_by_users]}")
        print(f"[MESSAGE STATUS] Read by count: {read_by_count}, Delivered to count: {delivered_to_count}, Total members: {total_members}")
        if total_members > 0 and len(read_by_users) == total_members:
            return "read"
        elif delivered_to_count > 0:
            return "delivered"
        else:
            return "sent"

    async def mark_message_as_read(self, message_id):
        try:
            message = await self.get_message(message_id)
        except GroupMessage.DoesNotExist:
            return

        user = self.scope["user"]

        # Check if the user has already read the message
        if user in await self.get_message_read_by(message):
            return

        # Add the user to the read_by list
        await self.add_message_to_read_by(message, user)

        # Consistent status calculation
        status = await self.get_message_status(message)

        # Broadcast the status update to the group
        await self.channel_layer.group_send(
            self.chatroom_name,
            {
                "type": "chat_message_status",
                "message_id": message_id,
                "status": status,
            }
        )

        print(f"[MESSAGE READ] Message {message_id} marked as {status} by {user.username}")