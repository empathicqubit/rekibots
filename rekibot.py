import ananas
import random
import sqlite3
import urllib.request
from pybooru import Danbooru
import magic
import time
import re
import sys
from datetime import datetime
from html.parser import HTMLParser

class reminder(ananas.PineappleBot):
    def start(self):
        if "log_file" in self.config and len(self.config.log_file)>0:
            self.log_file = open(self.config.log_file, "a")
        else:
            self.log_file = sys.stdout
        self.me = self.mastodon.account_verify_credentials()
        self.last_checked_post = self.mastodon.timeline_home()[0]
        self.h = HTMLParser()
    
    @ananas.schedule(minute="*", second=30)
    def check_follows(self):
        try:
            self.me = self.mastodon.account_verify_credentials()
            my_id = self.me['id']
            followers_count = self.me['followers_count']
            followers = self.mastodon.account_followers(my_id,limit=80)
            if len(followers)<followers_count:
                followers = self.mastodon.fetch_remaining(followers)
            following_count = self.me['following_count']
            following = self.mastodon.account_following(my_id,limit=80)
            if len(following)<following_count:
                following = self.mastodon.fetch_remaining(following)
            followingids=[]
            for followed in following:
                followingids=followingids+[followed['id'],]
            followerids=[]
            for follower in followers:
                followerids=followerids+[follower['id'],]
            for follower in followerids:
                if follower not in followingids:
                    time.sleep(1)
                    if not self.mastodon.account_relationships(follower)[0]['requested']:
                        if "moved" in self.mastodon.account(follower):
                            self.mastodon.account_block(follower)
                            self.mastodon.account_unblock(follower)
                            print("[{0:%Y-%m-%d %H:%M:%S}] {1}.check_follows: Softblocked user {2}.".format(datetime.now(),self.config._name,str(follower)), file=self.log_file, flush=True)
                        else:
                            ret=self.mastodon.account_follow(follower,reblogs=False)
                            print("[{0:%Y-%m-%d %H:%M:%S}] {1}.check_follows: Attempted to follow user {2}.".format(datetime.now(),self.config._name,str(follower)), file=self.log_file, flush=True)
            for followed in followingids:
                if followed not in followerids:
                    time.sleep(1)
                    if not self.mastodon.account_relationships(followed)[0]['requested']:
                        self.mastodon.account_unfollow(followed) 
                        print("[{0:%Y-%m-%d %H:%M:%S}] {1}.check_follows: Unfollowed user {2}.".format(datetime.now(),self.config._name,str(followed)), file=self.log_file, flush=True)
        except Exception as e:
            print("[{0:%Y-%m-%d %H:%M:%S}] {1}.check_follows: {2}".format(datetime.now(),self.config._name,e), file=self.log_file, flush=True)
   
    @ananas.schedule(minute="*", second=0)
    def check_posts(self):
        posts = self.mastodon.timeline_home(since_id=self.last_checked_post['id'])
        if len(posts)>0:
            for post in posts:
                if len(post['media_attachments'])>0 and post['reblog'] is None and post['in_reply_to_id'] is None and not "RT @" in post['content']:
                    marked = False
                    for attachment in post['media_attachments']:
                        if attachment['description'] is None:
                            marked = True
                    if marked:
                        print("[{0:%Y-%m-%d %H:%M:%S}] {1}.check_posts: -> Posting reply.".format(datetime.now(),self.config._name), file=self.log_file, flush=True)
                        self.mastodon.status_post('@'+post['account']['acct']+' hey, just so you know, this status includes an attachment with missing accessibility (alt) text.', in_reply_to_id=(post['id']),visibility='direct')
            self.last_checked_post = posts[0]
            
    @ananas.reply
    def delete_post(self, status, user):
        if user['acct'] == self.config.admin:
            if 'delete this!' in status['content']:
                self.mastodon.status_delete(status['in_reply_to_id'])
            elif '!announce' in status['content']:
                text = re.sub('<[^<]+?>', '', status['content'])
                text = self.h.unescape(text)
                self.mastodon.status_post(text.split('announce! ')[-1], in_reply_to_id=None, media_ids=None, sensitive=False, visibility="unlisted", spoiler_text=None)
      
class danboorubot(ananas.PineappleBot):
    def start(self):
        if "log_file" in self.config and len(self.config.log_file)>0:
            self.log_file = open(self.config.log_file, "a")
        else:
            self.log_file = sys.stdout
        self.mime = magic.Magic(mime=True)
        self.proxy = urllib.request.ProxyHandler({})
        self.opener = urllib.request.build_opener(self.proxy)
        self.opener.addheaders = [('User-Agent','Mozilla/5.0 (Macintosh; Intel Mac OS X 10_12_4) AppleWebKit/603.1.30 (KHTML, like Gecko) Version/10.1 Safari/603.1.30')]
        urllib.request.install_opener(self.opener)
        self.client = Danbooru(site_url='https://safebooru.donmai.us')
        self.h = HTMLParser()
        
        self.queue=[]
        
        self.tags = self.config.tags.split(',')
        
        self.blacklist_tags = ['spoilers','guro','bdsm','bondage','foot_worship','comic','naked_sheet','foot_licking','nude','nude_cover','randoseru','kindergarten_uniform',
                               'male_focus','1boy','2boys','3boys','4boys','5boys','6+boys','multiple_boys','horror','parody','no_humans','manly','banned_artist',
                               'swastika','nazi','ss_insignia','everyone','giantess']
        self.mandatory_tags = ['1girl','2girls','3girls','4girls','5girls','6+girls','multiple_girls']
        self.skip_tags = ['touhou','mahou_shoujo_madoka_magica','santa_costume']
        
        self.skip_chance = 75
        self.max_page = 300
        self.max_badpages = 10    
        self.queue_length = 5
        self.post_every = 30
        self.offset = 0
        
        #can probably replace this with a loop later
        if 'blacklist_tags' in self.config and len(self.config.blacklist_tags)>0:
            self.blacklist_tags = self.blacklist_tags + self.config.blacklist_tags.split(',')
        if 'mandatory_tags' in self.config and len(self.config.mandatory_tags)>0:
            self.mandatory_tags = self.mandatory_tags + self.config.mandatory_tags.split(',')
        if 'skip_tags' in self.config and len(self.config.skip_tags)>0:
            self.skip_tags = self.skip_tags + self.config.skip_tags.split(',')
        if 'skip_chance' in self.config and len(self.config.skip_chance)>0:
            self.skip_chance = int(self.config.skip_chance)
        if 'max_page' in self.config and len(self.config.max_page)>0:
            self.max_page = int(self.config.max_page)
        if 'max_badpages' in self.config and len(self.config.max_badpages)>0:
            self.max_badpages = int(self.config.max_badpages)
        if 'queue_length' in self.config and len(self.config.queue_length)>0:
            self.queue_length = int(self.config.queue_length)
        if 'post_every' in self.config and len(self.config.post_every)>0:
            self.post_every = int(self.config.post_every)
        if 'offset' in self.config and len(self.config.offset)>0:
            self.offset = int(self.config.offset)
        
        self.create_table_sql = "create table if not exists images (danbooru_id integer primary key,url_danbooru text,url_source text,tags text,posted integer default 0,blacklisted integer default 0,UNIQUE(url_danbooru),UNIQUE(url_source));"
        self.insert_sql = "insert into images(danbooru_id,url_danbooru,url_source,tags) values(?,?,?,?);"
        self.select_sql = "select danbooru_id,url_danbooru,url_source,tags from images where blacklisted=0 and posted=0;"
        self.blacklist_sql = "update images set blacklisted=1 where danbooru_id=?;"
        self.unmark_sql = "update images set posted=0;"
        self.mark_sql = "update images set posted=1 where danbooru_id=?;"
        self.migrate_db_sql1 = "alter table images rename to images_old;"
        self.migrate_db_sql2 = "update images set blacklisted=1 where danbooru_id in (select danbooru_id from images_old where blacklisted=1);"
        self.migrate_db_sql3 = "update images set posted=1 where danbooru_id in (select danbooru_id from images_old where posted=1);"
        self.migrate_db_sql4 = "drop table images_old;"
        
        conn = sqlite3.connect("{0}.db".format(self.config._name))
        cur = conn.cursor()
        
        if 'migratedb' in self.config and self.config.migratedb == "yes":
            try:
                print("[{0:%Y-%m-%d %H:%M:%S}] {1}.start: ALTER TABLE images RENAME TO images_old;".format(datetime.now(),self.config._name), file=self.log_file, flush=True)
                cur.execute(self.migrate_db_sql1)
            except Exception as e:
                print("[{0:%Y-%m-%d %H:%M:%S}] {1}.start: {2}".format(datetime.now(),self.config._name,e), file=self.log_file, flush=True)
                conn.rollback()
                conn.close()
                return
                
        cur.execute(self.create_table_sql)
        conn.commit()
        conn.close()
        
        conn = sqlite3.connect("{0}.db".format(self.config._name))
        cur = conn.cursor()
        
        cur.execute(self.select_sql)
        if len(cur.fetchall())==0:
            self.check_booru()
        conn.close()
        
        if 'migratedb' in self.config and self.config.migratedb == "yes":
            conn = sqlite3.connect("{0}.db".format(self.config._name))
            cur = conn.cursor()
            try:
                print("[{0:%Y-%m-%d %H:%M:%S}] {1}.start: UPDATE images SET blacklisted=1 WHERE danbooru_id IN (SELECT danbooru_id FROM images_old WHERE blacklisted=1);".format(datetime.now(),self.config._name), file=self.log_file, flush=True)
                cur.execute(self.migrate_db_sql2)
                print("[{0:%Y-%m-%d %H:%M:%S}] {1}.start: UPDATE images SET posted=1 WHERE danbooru_id IN (SELECT danbooru_id FROM images_old WHERE posted=1);".format(datetime.now(),self.config._name), file=self.log_file, flush=True)
                cur.execute(self.migrate_db_sql3)
                print("[{0:%Y-%m-%d %H:%M:%S}] {1}.start: DROP TABLE images_old;".format(datetime.now(),self.config._name), file=self.log_file, flush=True)
                cur.execute(self.migrate_db_sql4)
            except Exception as e:
                print("[{0:%Y-%m-%d %H:%M:%S}] {1}.start: {2}".format(datetime.now(),self.config._name,e), file=self.log_file, flush=True)
                conn.rollback()
                conn.close()
                return
                
            conn.commit()
            conn.close()
            print("[{0:%Y-%m-%d %H:%M:%S}] {1}.start: Database rebuild with migration completed OK.".format(datetime.now(),self.config._name), file=self.log_file, flush=True)
            self.config.migratedb="no"
            
    def check_booru(self):
        conn = sqlite3.connect("{0}.db".format(self.config._name))
        cur = conn.cursor()
        for t in self.tags:
            print("[{0:%Y-%m-%d %H:%M:%S}] {1}.check_booru: Pulling from tag '{2}'.".format(datetime.now(),self.config._name,t), file=self.log_file, flush=True)
            badpages=0
            for page in range(1,self.max_page+1):
                while True:
                    try:
                        posts = self.client.post_list(tags=t, page=str(page), limit=200)
                    except:
                        continue
                    else:
                        break
                if len(posts) == 0:
                    print("[{0:%Y-%m-%d %H:%M:%S}] {1}.check_booru: No more posts. Break processing.".format(datetime.now(),self.config._name), file=self.log_file, flush=True)
                    break
                counter=0
                for post in posts:
                    if (('drawfag' not in post['source'] and '.png' not in post['source'] and '.jpg' not in post['source'] and '.gif' not in post['source'] and post['source'] != '') or post['pixiv_id'] is not None) and post['is_deleted']==False and not any(tag in post['tag_string'].split(" ") for tag in self.blacklist_tags) and any(tag in post['tag_string'].split(" ") for tag in self.mandatory_tags):
                        if post['pixiv_id'] is not None:
                            source_url = 'https://www.pixiv.net/artworks/{0}'.format(post['pixiv_id'])
                        else:
                            source_url = post['source']
                        if 'file_url' in post:
                            danbooru_url = post['file_url']
                        elif 'large_file_url' in post:
                            danbooru_url = post['large_file_url']
                        else:
                            continue
                        try:
                            cur.execute(self.insert_sql, (int(post['id']),danbooru_url,source_url,post['tag_string']))
                        except:
                            continue
                        else:
                            counter=counter+1
                print("[{0:%Y-%m-%d %H:%M:%S}] {1}.check_booru: Page {2} - inserted {3} entries.".format(datetime.now(),self.config._name,page,counter), file=self.log_file, flush=True)
                if counter == 0:
                    badpages = badpages+1
                    if badpages == self.max_badpages:
                        print("[{0:%Y-%m-%d %H:%M:%S}] {1}.check_booru: No new posts on {2} pages in a row. Break processing.".format(datetime.now(),self.config._name,badpages), file=self.log_file, flush=True)
                        break
                else:
                    badpages = 0
        conn.commit()
        conn.close()
        
    def blacklist(self,id):
        conn = sqlite3.connect("{0}.db".format(self.config._name))
        cur = conn.cursor()
        cur.execute(self.blacklist_sql, (id,))
        conn.commit()
        conn.close()
        print("[{0:%Y-%m-%d %H:%M:%S}] {1}.blacklist: Blacklisted http://danbooru.donmai.us/posts/{2}".format(datetime.now(),self.config._name,id), file=self.log_file, flush=True)
        
    @ananas.schedule(minute="*")
    def post(self):
        if not any(datetime.now().minute==x+self.offset for x in range(0,60,self.post_every)):
            return
        while True:
            while len(self.queue) == 0:
                conn = sqlite3.connect("{0}.db".format(self.config._name))
                cur = conn.cursor()
                cur.execute(self.select_sql)
                self.queue = cur.fetchall()
                random.shuffle(self.queue)
                self.queue = self.queue[:self.queue_length]
                if len(self.queue) == 0:
                    print("[{0:%Y-%m-%d %H:%M:%S}] {1}.post: No valid entries. Resetting db.".format(datetime.now(),self.config._name), file=self.log_file, flush=True)
                    cur.execute(self.unmark_sql)
                    conn.commit()
                else:
                    cur.executemany(self.mark_sql, [(str(item[0]),) for item in self.queue])
                    conn.commit()
                conn.close()
                print("[{0:%Y-%m-%d %H:%M:%S}] {1}.post: Refilled queue with {2} entries.".format(datetime.now(),self.config._name,len(self.queue)), file=self.log_file, flush=True)
            id,url,src,tags = self.queue.pop()
            if any(tag in tags.split(" ") for tag in self.blacklist_tags):
                self.blacklist(id)
                continue
            if any(tag in tags.split(" ") for tag in self.skip_tags):
                if random.randint(1,100) <= self.skip_chance:
                    print("[{0:%Y-%m-%d %H:%M:%S}] {1}.post: Skipped {2}.".format(datetime.now(),self.config._name,id), file=self.log_file, flush=True)
                    continue
            try:
                url = urllib.request.urlretrieve(url)[0]
                with open(url,'rb') as file:
                    mediadict = self.mastodon.media_post(file.read(),self.mime.from_file(url))
                status_text = 'http://danbooru.donmai.us/posts/{0}\r\nsource: {1}'.format(id,src)
                self.mastodon.status_post(status_text, in_reply_to_id=None, media_ids=(mediadict['id'],), sensitive=True, visibility="unlisted", spoiler_text=None)
            except Exception as e:
                print("[{0:%Y-%m-%d %H:%M:%S}] {1}.post: Post http://danbooru.donmai.us/posts/{2} threw exception: {3}".format(datetime.now(),self.config._name,id,e), file=self.log_file, flush=True)
                continue
            else:
                print("[{0:%Y-%m-%d %H:%M:%S}] {1}.post: Posted.".format(datetime.now(),self.config._name), file=self.log_file, flush=True)
                break

    @ananas.schedule(hour="*/6", minute=10)
    def update_db(self):
        self.check_booru()  

    @ananas.reply
    def handle_reply(self, status, user):
        if user['acct'] == self.config.admin:
            if 'delete this!' in status['content']:
                status_in_question = self.mastodon.status(status['in_reply_to_id'])
                self.mastodon.status_delete(status['in_reply_to_id'])
                text = re.sub('<[^<]+?>', '', status_in_question['content'])
                text = self.h.unescape(text)
                id = re.search("posts\/([0-9]+)source",text)
                id = id.groups()[0]
                self.blacklist(id)
            elif 'announce! ' in status['content']:
                text = re.sub('<[^<]+?>', '', status['content'])
                text = self.h.unescape(text)
                self.mastodon.status_post(text.split('announce! ')[-1], in_reply_to_id=None, media_ids=None, sensitive=False, visibility="unlisted", spoiler_text=None)
        

class admin_cleaner(ananas.PineappleBot):
    def start(self):
        if "log_file" in self.config and len(self.config.log_file)>0:
            self.log_file = open(self.config.log_file, "a")
        else:
            self.log_file = sys.stdout
        self.me = self.mastodon.account_verify_credentials()
        self.last_checked_post = self.mastodon.timeline_home()[0]

    @ananas.schedule(minute=0)
    def check_posts(self):
        posts = self.mastodon.account_statuses(self.me['id'],since_id=self.last_checked_post)
        if len(posts)>0:
            for post in posts:
                if "delete this!" in post['content']:
                    self.mastodon.status_delete(post['id'])
                    print("[{0:%Y-%m-%d %H:%M:%S}] {1}.check_posts: Found deleter post id {2}.".format(datetime.now(),self.config._name,post['id']), file=self.log_file, flush=True)
                if "announce! " in post['content']:
                    self.mastodon.status_delete(post['id'])
                    print("[{0:%Y-%m-%d %H:%M:%S}] {1}.check_posts: Found announcer post id {2}.".format(datetime.now(),self.config._name,post['id']), file=self.log_file, flush=True)
            self.last_checked_post = posts[0]
