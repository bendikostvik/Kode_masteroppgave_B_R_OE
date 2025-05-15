""" Et program som tar inn data for prediksjoner på pris og frekvensavvik for en dag 
 og kjører en optimeringsfunksjon for å finne optimale budpriser og volum
 for en batteriinstallasjon på 2 MWh.
"""
from pyomo.environ import *
import pandas as pd


# konstanter ###########################################################
## antatte batterikostnader
installert_kap = 2.5 # MW
installert_kap_MWh = 2 # MWh
kap_vann = 0.7 # [MW]
tapsfaktor = 1.075 # [MWh/MWh]
investeringskostnad = 500000 # EUR/MWh
spenning = 1000 # V
DOD_faktor = 0.0008 # ?
C_faktor = 0.4 # ?
b = 1
kalendertap = 0.00014 / 24 # [MWh/MWh]
EOL_kapasitet_andel = 0.2 # [%]
total_Ah_throughput = 3000000*15 # [Ah/MWh] 

# funkjsoner ###########################################################

## hvor mye effekt batteriet må levere
def volum_effekt_N(model):
    avvik = value(model.frekvensavvik)
    if avvik < -0.1:
        avvik = -0.1
    elif avvik > 0.1:
        avvik = 0.1
    return model.innbydd_effekt_N * abs(avvik) * 10 *  tapsfaktor, avvik * model.innbydd_effekt_N * 10 # [MWh/h]



## kostnad og inntekt
def C_rate(model):
    abs_avvik, avvik = volum_effekt_N(model)

    return (abs_avvik) * model.innbydd_effekt_N / installert_kap # [MW/MW]

def ladning(model):
    abs_volum, volum = volum_effekt_N(model)

    return model.innbydd_effekt_N * (abs_volum) * 60 / spenning  # [Ah]

def syklustap(model):
    return ladning(model)**b * DOD_faktor * exp(C_faktor * C_rate(model)) # [MWh/MWh]

def kostnad(model):
    return (syklustap(model) / EOL_kapasitet_andel + kalendertap) * investeringskostnad * installert_kap ## [EUR]

def inntekt_halvD(model):
    return (model.innbydd_effekt_N + model.deltakelse_vann_N * kap_vann) * model.markedspris # [EUR]

def kostnad_vann(model):
    return (model.spotpris) * (model.deltakelse_vann_N) * kap_vann # [EUR]


## Markedsreguleringer og kapasitet

def SOC_delta(model):
    abs_volum, volum = volum_effekt_N(model)

    return (volum) / installert_kap 

def reservert_P_N(model):
    return model.innbydd_effekt_N * 1.34 + model.deltakelse_vann_N * kap_vann # [MW]


def reservert_effekt_oppregulering(model):
    return reservert_P_N(model) 

def reservert_effekt_nedregulering(model):
    return reservert_P_N(model) 

def reservert_energi_oppregulering(model):
    return model.innbydd_effekt_N + model.deltakelse_vann_N * kap_vann # [MWh]

def reservert_energi_nedregulering(model):
    return model.innbydd_effekt_N + model.deltakelse_vann_N * kap_vann # [MWh]

def reservert_energi_oppregulering_batteri(model):
    return model.innbydd_effekt_N # [MWh]

def reservert_energi_nedregulering_batteri(model):
    return model.innbydd_effekt_N # [MWh]




# modell ############################################################

def make_model(markedspris, frekvensavvik, spotpris, SOC):
    model = ConcreteModel()
    solver = SolverFactory('ipopt')

    # Variables ############################################################
    model.bud_pris_N = Var(bounds = (5, 100), initialize=40) # EUR/MW

    model.innbydd_effekt_N = Var(initialize=1.8) # MW

    model.deltakelse_vann_N = Var(bounds = (0, 1), initialize= 0.5) # MW

    model.frekvensavvik = Param(initialize=frekvensavvik, mutable=True) # Hz
    model.markedspris = Param(initialize=markedspris, mutable=True) # EUR/MW

    model.spotpris = Param(initialize=spotpris, mutable=True) # EUR/MW
    model.SOC = Param(initialize=SOC, mutable=True) # MWh


    # Constraints ###########################################################
    model.c = ConstraintList()
    model.c.add(model.bud_pris_N >= 5)
    model.c.add(model.bud_pris_N <= model.markedspris)

    model.c.add(model.innbydd_effekt_N >= 0)


    model.c.add(model.innbydd_effekt_N * 1.07 <= installert_kap) #* snitt_volum_pris(model)
    model.c.add(model.innbydd_effekt_N * 1.07 <= installert_kap) #* snitt_volum_pris(model)

    model.c.add(model.deltakelse_vann_N >= 0)


    model.c.add(model.deltakelse_vann_N <= 1)


    model.c.add(model.SOC + SOC_delta(model) <= 0.9)
    model.c.add(model.SOC + SOC_delta(model) >= 0.1)

    model.c.add(model.deltakelse_vann_N <= 1) # [MW]

    model.c.add(reservert_effekt_oppregulering(model) <= installert_kap + kap_vann) # [MW]
    model.c.add(reservert_effekt_nedregulering(model) <= installert_kap + kap_vann) # [MW]
    model.c.add(reservert_effekt_oppregulering(model) <= 3.2) # [MW]
    model.c.add(reservert_effekt_nedregulering(model) <= 3.2)    

    model.c.add(reservert_energi_oppregulering_batteri(model) <= installert_kap_MWh * 0.5 * (1 - (model.SOC - 0.5)) + kap_vann) # [MWh], betydningen av vann gir ikke helt mening men må være representert på et vis
    model.c.add(reservert_energi_nedregulering_batteri(model) <= installert_kap_MWh * 0.5 * (1 - (0.5 - model.SOC)) + kap_vann) # [MWh], betydningen av vann gir ikke helt mening men må være representert på et vis




    # Objective ############################################################
    model.obj = Objective(expr= (inntekt_halvD(model) - kostnad(model) - kostnad_vann(model)), sense=maximize)
    

    return model, solver

def optimal_fortjeneste(pris, avvik, spotpris, SOC):
    # create model
    model, solver = make_model(pris, avvik, spotpris, SOC)

    # Solve the model for every hour 
    results = solver.solve(model, tee=True)
    print("SOC delta:", value(SOC_delta(model)))


    return value(model.innbydd_effekt_N), value(model.bud_pris_N), value(model.obj), value(model.deltakelse_vann_N), value(kostnad(model)), value(model.innbydd_effekt_N * model.markedspris), value(inntekt_halvD(model)), value(SOC_delta(model) + model.SOC), value(kostnad_vann(model))


def read_csv(csv):
    dag_df = pd.read_csv(f'{csv}', sep=';')
    dag_df['Pris'] = dag_df['Pris'].astype(float)
    dag_df['Frekvensavvik'] = dag_df['Frekvensavvik'].astype(float)
    dag_df['Pris_D'] = dag_df['Pris_D'].astype(float)
    return dag_df

def run_model_dag(csv_or_pandas, csv = True, SOC = 0.5):
    if csv:
        dag_df = read_csv(csv_or_pandas)
    else:
        dag_df = csv_or_pandas
    # apply the model ##############################################
    results = []
    result_bud_pris = []
    result_bud_volum = []
    results_vann = []
    result_kostnad = []
    result_SOC = []
    result_inntekt_batteri = []

    result_inntekt_total = []
    result_kost_vann = []

    SOC_loop = SOC

    for idx, row in dag_df.iterrows():
        pris = row['Pris']

        avvik = row['Frekvensavvik']
        spotpris = row['spotpris'] 


        # Solve the model
        effekten, budprisen, overskuddet, deltakelsen_vann, kostnad_batteri, inntekt_batteri, inntekt_total, SOC_etter, kostnad_vann = optimal_fortjeneste(pris, avvik, spotpris, SOC_loop)
        SOC_loop = SOC_etter
        

        results.append(overskuddet)
        result_bud_pris.append(budprisen)
        result_bud_volum.append(effekten)
        results_vann.append(deltakelsen_vann)
        result_kostnad.append(kostnad_batteri)
        result_inntekt_batteri.append(inntekt_batteri)
        result_SOC.append(SOC_etter)
        result_inntekt_total.append(inntekt_total)
        result_kost_vann.append(kostnad_vann)
        print(row.index)



    dag_df['Optimal Budpris'] = result_bud_pris
    dag_df['Optimal Budvolum'] = result_bud_volum
    dag_df['Optimalt Overskudd'] = results
    dag_df['Optimal Deltakelse Vann'] = results_vann
    dag_df['Kostnad Batteri'] = result_kostnad
    dag_df['Inntekt FCR'] = result_inntekt_batteri
    dag_df['Inntekt Total'] = result_inntekt_total
    dag_df['SOC'] = result_SOC
    dag_df['Kostnad Vann'] = result_kost_vann
    return dag_df