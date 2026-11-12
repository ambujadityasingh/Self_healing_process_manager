from flask import Flask, jsonify, render_template

def create_app(manager):
    app=Flask(__name__)
    @app.get('/')
    def index(): return render_template('index.html')
    @app.get('/api/state')
    def state():
        activity=manager.activity_provider.snapshot(); rows=[]
        for pid,t in list(manager.targets.items()):
            try: rows.append(manager.sample(pid,activity))
            except Exception: rows.append({'pid':pid,'name':t['name'],'status':'exited','cpu_percent':0,'memory_mb':0,'foreground':None,'user_idle_seconds':activity.idle_seconds})
        return jsonify({'activity':activity.as_dict(),'processes':rows,'samples':manager.store.rows('samples',40),'incidents':manager.store.rows('incidents',20),'actions':manager.store.rows('actions',20)})
    return app
