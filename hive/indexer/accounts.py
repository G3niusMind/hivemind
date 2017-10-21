import time

from hive.db.methods import query_one, query_col, query, query_row, query_all
from hive.indexer.utils import get_adapter
from hive.indexer.normalize import rep_log10, amount, trunc

class Accounts:
    _ids = {}
    _dirty = set()

    # account core methods
    # --------------------

    @classmethod
    def load_ids(cls):
        assert not cls._ids, "id map only needs to be loaded once"
        cls._ids = dict(query_all("SELECT name, id FROM hive_accounts"))

    @classmethod
    def get_id(cls, name):
        assert name in cls._ids, "account does not exist or was not registered"
        return cls._ids[name]

    @classmethod
    def exists(cls, name):
        return (name in cls._ids)

    @classmethod
    def register(cls, names, block_date):
        new_names = []
        for name in set(names):
            if not cls.exists(name):
                new_names.append(name)
        if not new_names:
            return

        # insert new names and add the new ids to our mem map
        for name in new_names:
            query("INSERT INTO hive_accounts (name, created_at) "
                    "VALUES (:name, :date)", name=name, date=block_date)

        sql = "SELECT name, id FROM hive_accounts WHERE name IN :names"
        cls._ids = {**dict(query_all(sql, names=new_names)), **cls._ids}


    # account cache methods
    # ---------------------

    @classmethod
    def dirty(cls, account):
        cls._dirty.add(account)

    @classmethod
    def cache_all(cls):
        cls.cache_accounts(query_col("SELECT name FROM hive_accounts"))

    @classmethod
    def cache_dirty(cls):
        cls.cache_accounts(cls._dirty)
        cls._dirty = set()

    @classmethod
    def cache_accounts(cls, accounts):
        from hive.indexer.cache import batch_queries

        processed = 0
        total = len(accounts)

        for i in range(0, total, 1000):
            batch = accounts[i:i+1000]

            lap_0 = time.time()
            sqls = cls._generate_cache_sqls(batch)
            lap_1 = time.time()
            batch_queries(sqls)
            lap_2 = time.time()

            processed += len(batch)
            rem = total - processed
            rate = len(batch) / (lap_2 - lap_0)
            pct_db = int(100 * (lap_2 - lap_1) / (lap_2 - lap_0))
            print(" -- {} of {} ({}/s, {}% db) -- {}m remaining".format(
                processed, total, round(rate, 1), pct_db, round(rem / rate / 60, 2)))

    @classmethod
    def _generate_cache_sqls(cls, accounts):
        fstats = cls._get_accounts_follow_stats(accounts)
        sqls = []
        for account in get_adapter().get_accounts(accounts):
            name = account['name']

            values = {
                'name': name,
                'proxy': account['proxy'],
                'post_count': account['post_count'],
                'reputation': rep_log10(account['reputation']),
                'followers': fstats['followers'][name],
                'following': fstats['following'][name],
                'proxy_weight': amount(account['vesting_shares']),
                'vote_weight': amount(account['vesting_shares']),
                'kb_used': int(account['lifetime_bandwidth']) / 1e6 / 1024,
                **cls._safe_account_metadata(account)
            }

            update = ', '.join([k+" = :"+k for k in values.keys()][1:])
            sql = "UPDATE hive_accounts SET %s WHERE name = :name" % (update)
            sqls.append([(sql, values)])
        return sqls

    @classmethod
    def _get_accounts_follow_stats(cls, accounts):
        sql = """SELECT follower, COUNT(*) FROM hive_follows
                WHERE follower IN :lst GROUP BY follower"""
        following = dict(query(sql, lst=accounts).fetchall())
        for name in accounts:
            if name not in following:
                following[name] = 0

        sql = """SELECT following, COUNT(*) FROM hive_follows
                WHERE following IN :lst GROUP BY following"""
        followers = dict(query(sql, lst=accounts).fetchall())
        for name in accounts:
            if name not in followers:
                followers[name] = 0

        return {'followers': followers, 'following': following}

    @classmethod
    def _safe_account_metadata(cls, account):
        prof = {}
        try:
            prof = json.loads(account['json_metadata'])['profile']
            if not isinstance(prof, dict):
                prof = {}
        except:
            pass

        name = str(prof['name']) if 'name' in prof else None
        about = str(prof['about']) if 'about' in prof else None
        location = str(prof['location']) if 'location' in prof else None
        website = str(prof['website']) if 'website' in prof else None
        profile_image = str(prof['profile_image']) if 'profile_image' in prof else None
        cover_image = str(prof['cover_image']) if 'cover_image' in prof else None

        name = trunc(name, 20)
        about = trunc(about, 160)
        location = trunc(location, 30)

        if name and name[0:1] == '@':
            name = None
        if website and len(website) > 100:
            website = None
        if website and website[0:4] != 'http':
            website = 'http://' + website
        # TODO: regex validate `website`

        if profile_image and not re.match('^https?://', profile_image):
            profile_image = None
        if cover_image and not re.match('^https?://', cover_image):
            cover_image = None
        if profile_image and len(profile_image) > 1024:
            profile_image = None
        if cover_image and len(cover_image) > 1024:
            cover_image = None

        return dict(
            display_name=name or '',
            about=about or '',
            location=location or '',
            website=website or '',
            profile_image=profile_image or '',
            cover_image=cover_image or '',
        )


if __name__ == '__main__':
    sqls = Accounts._generate_cache_sqls(['roadscape', 'ned', 'sneak', 'test-safari'])
    print(sqls)
    #Accounts.cache_all()
