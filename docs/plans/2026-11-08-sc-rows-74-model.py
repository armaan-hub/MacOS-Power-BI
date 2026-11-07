from tests import critic3_models as m
import random
random.seed(83606)
DIM=[('Item','string'),('Fam','string'),('Tier','int64')]
dims=[('I%d'%i,random.choice(['G1','G2']),random.randint(1,3)) for i in range(1,7)]
FCT=[('Id','int64'),('Item','string'),('Dt','dateTime'),('Val','double'),('Units','int64')]
facts=[]
for i in range(1,27):
    r=random.random()
    item=None if r<0.08 else ('I%d'%random.randint(7,8) if r<0.25 else 'I%d'%random.randint(1,7))
    facts.append((i,item,(random.choice([2023,2024]),random.randint(1,12),random.randint(1,28)),None if random.random()<0.1 else float(random.randint(-10,90)),random.randint(0,9)))
m.SPEC['ZV']={'tables':{'ZV_Dim':(DIM,dims),'ZV_Fact':(FCT,facts),'ZV_Cal':(m.CAL_COLS,None)},
 'rels':[('ZV_r1','ZV_Fact','Item','ZV_Dim','Item',True,False,'many','one'),('ZV_r2','ZV_Fact','Dt','ZV_Cal','Date',True,False,'many','one')]}
