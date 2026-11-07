from tests import critic3_models as m
import random
random.seed(81303)
DIM=[('Item','string'),('Fam','string'),('Tier','int64')]
dims=[('I%d'%i,random.choice(['F1','F2','F3']),random.randint(1,3)) for i in range(1,8)]
FCT=[('Id','int64'),('Item','string'),('Dt','dateTime'),('Val','double'),('Units','int64')]
facts=[]
for i in range(1,23):
    r=random.random()
    item=None if r<0.08 else ('I%d'%random.randint(8,9) if r<0.25 else 'I%d'%random.randint(1,7))
    facts.append((i,item,(random.choice([2023,2024]),random.randint(1,12),random.randint(1,28)),None if random.random()<0.1 else float(random.randint(-10,90)),random.randint(0,9)))
m.SPEC['ZX']={'tables':{'ZX_Dim':(DIM,dims),'ZX_Fact':(FCT,facts),'ZX_Cal':(m.CAL_COLS,None)},
 'rels':[('ZX_r1','ZX_Fact','Item','ZX_Dim','Item',True,False,'many','one'),('ZX_r2','ZX_Fact','Dt','ZX_Cal','Date',True,False,'many','one')]}
