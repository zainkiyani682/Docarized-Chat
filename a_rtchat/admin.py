from django.contrib import admin
from .models import ChatGroup, GroupMessage

@admin.register(ChatGroup)
class ChatGroupAdmin(admin.ModelAdmin):
    list_display = ['id', 'group_name', 'groupchat_name', 'admin', 'is_private']
    search_fields = ['group_name', 'groupchat_name', 'admin__username']
    filter_horizontal = ['members', 'user_online']

@admin.register(GroupMessage)
class GroupMessageAdmin(admin.ModelAdmin):
    list_display = ['id', 'group', 'author', 'body', 'created', 'read']
    search_fields = ['body', 'author__username', 'group__group_name']
    list_filter = ['read', 'created']