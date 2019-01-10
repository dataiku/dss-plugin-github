import github
def do(payload, config):
    if not "login" in config or not "password" in config or not "repos" in config:
        return {
            "ok" : False,
            "message": "Missing important field"
        }
    try:
        gh = github.Github(config["login"], config["password"])
        gh.get_repo(config["repos"])
        return {
            "ok" : True
        }
    except Exception, e:
        return {
            "ok" : False,
            "message" : "Error: %s" % str(e)
        }