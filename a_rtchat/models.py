from django.db import models
from django.contrib.auth.models import User
import shortuuid
from django.utils import timezone

# Create your models here.
class ChatGroup(models.Model):
    group_name = models.CharField(max_length=128,unique=True)
    groupchat_name = models.CharField(max_length=128, null=True,blank=True)
    admin = models.ForeignKey(User,related_name='groupschat',blank=True, null=True, on_delete=models.SET_NULL)

    user_online = models.ManyToManyField(User,related_name='online_in_groups',blank=True, null=True)
    members = models.ManyToManyField(User,related_name='chat_group', blank=True)
    is_private = models.BooleanField(default=False)
    

    def __str__(self):
        return self.group_name
    def save(self,*args,**kwargs):
        if not self.group_name:
            self.group_name = shortuuid.uuid()
        super().save(*args,**kwargs)
class GroupMessage(models.Model):
    group = models.ForeignKey(ChatGroup, related_name='chat_message', on_delete=models.CASCADE)
    author = models.ForeignKey(User,on_delete=models.CASCADE)
    body = models.CharField(max_length=300)
    created = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    read = models.BooleanField(default=False)
    read_by = models.ManyToManyField(User, related_name='read_messages', blank=True)
    delivered_to = models.ManyToManyField(User, related_name='delivered_messages', blank=True)

    def is_fully_read(self):
        total = self.group.members.exclude(id=self.author.id).count()
        return self.read_by.exclude(id=self.author.id).count() == total
    

    def __str__(self):
        return f'{self.author.username} : {self.body}'

    class Meta:
        ordering = ['-created']
