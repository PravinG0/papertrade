"""Optional offline ML experiment. No model is loaded into production or used to trade."""
import argparse
import json
from pathlib import Path
from adaptive_memory import parse_time, number

# Fixed features available at decision time; never use exit prices, outcomes, target-hit status, or P&L as input.
FEATURES=('confidence','rsi','atr_pct','spread_pct','net_rr','ema_separation_atr')


def temporal_partitions(evaluations, minimum=300):
    rows=[]
    for row in evaluations:
        c,o=row.get('candidate',{}),row.get('outcome',{})
        decision=parse_time(c.get('decision_at')); available=parse_time(c.get('available_at')); end=parse_time(o.get('outcome_at'))
        feature_time=parse_time(c.get('features_at'))
        features=[number((c.get('features') or {}).get(k)) for k in FEATURES]
        pnl=number(o.get('net_pnl'))
        if o.get('status')!='resolved' or not decision or not available or not end or not feature_time or not feature_time<=decision<=available<end or None in features or pnl is None: continue
        rows.append((decision,end,features,int(pnl>0)))
    rows.sort(key=lambda r:r[0]); dates=sorted({r[0].date() for r in rows})
    if len(rows)<minimum or len(dates)<20: raise ValueError('Need at least 300 resolved feature-complete examples across 20 dates (research minimum).')
    a,b=dates[int(len(dates)*.6)],dates[int(len(dates)*.8)]
    train=[r for r in rows if r[0].date()<a and r[1].date()<a]
    calibration=[r for r in rows if a<=r[0].date()<b and r[1].date()<b]
    test=[r for r in rows if r[0].date()>=b]
    for part in (train,calibration,test):
        if len(part)<30 or len({r[3] for r in part})!=2: raise ValueError('Each chronological partition needs at least 30 observations and both classes after purging.')
    return train,calibration,test


def evaluate_ml(evaluations, model='logistic'):
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
    import numpy as np
    train,cal,test=temporal_partitions(evaluations)
    x=lambda rows:np.array([r[2] for r in rows]); y=lambda rows:np.array([r[3] for r in rows])
    if model=='logistic': base=make_pipeline(StandardScaler(),LogisticRegression(max_iter=1000,random_state=1))
    elif model=='xgboost':
        from xgboost import XGBClassifier
        base=XGBClassifier(n_estimators=100,max_depth=3,learning_rate=.05,random_state=1,n_jobs=1)
    elif model=='lightgbm':
        from lightgbm import LGBMClassifier
        base=LGBMClassifier(n_estimators=100,max_depth=3,learning_rate=.05,random_state=1,n_jobs=1,verbosity=-1)
    else: raise ValueError('Unknown model')
    base.fit(x(train),y(train))
    # Calibrate on a distinct period; final test is never used in fitting or calibration.
    transform=lambda p:np.log(np.clip(p,1e-6,1-1e-6)/np.clip(1-p,1e-6,1-1e-6)).reshape(-1,1)
    calibrator=LogisticRegression(max_iter=1000).fit(transform(base.predict_proba(x(cal))[:,1]),y(cal))
    raw=base.predict_proba(x(test))[:,1]; calibrated=calibrator.predict_proba(transform(raw))[:,1]; actual=y(test)
    metric=lambda p:{'brier':float(brier_score_loss(actual,p)),'log_loss':float(log_loss(actual,p)), 'roc_auc':float(roc_auc_score(actual,p))}
    return {'model':model,'features':FEATURES,'train':len(train),'calibration':len(cal),'unseen_test':len(test),
            'train_end':train[-1][0].isoformat(),'test_start':test[0][0].isoformat(), 'raw_metrics':metric(raw),'calibrated_metrics':metric(calibrated),
            'constant_baseline':metric(np.full(len(test),float(y(train).mean()))),
            'status':'research_only','warning':'One chronological holdout is not full walk-forward or prospective verification. Never promote automatically.'}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('research_report',type=Path);p.add_argument('--model',choices=['logistic','xgboost','lightgbm'],default='logistic');p.add_argument('--output',type=Path,required=True)
    a=p.parse_args(); report=json.loads(a.research_report.read_text()); a.output.write_text(json.dumps(evaluate_ml(report['evaluations'],a.model),indent=2,allow_nan=False))
