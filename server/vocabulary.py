# SPDX-FileCopyrightText: 2026 Luis Garbayo <lugarbayo@gmail.com>
#
# SPDX-License-Identifier: MIT

"""One bilingual vocabulary for all 80 COCO classes, display and parsing."""
import re
import unicodedata

# canonical | Spanish noun with article | extra aliases (accent-insensitive)
_ROWS = '''person|la persona|alguien,gente,hombre,mujer
bicycle|la bicicleta|bici
car|el coche|auto,carro
motorcycle|la moto|motocicleta
airplane|el avión|aeroplano
bus|el autobús|autocar
train|el tren|
truck|el camión|
boat|el barco|bote
traffic light|el semáforo|
fire hydrant|la boca de incendios|hidrante
stop sign|la señal de stop|stop
parking meter|el parquímetro|
bench|el banco|
bird|el pájaro|ave
cat|el gato|
dog|el perro|
horse|el caballo|
sheep|la oveja|
cow|la vaca|
elephant|el elefante|
bear|el oso|
zebra|la cebra|
giraffe|la jirafa|
backpack|la mochila|
umbrella|el paraguas|
handbag|el bolso|
tie|la corbata|
suitcase|la maleta|
frisbee|el frisbi|disco volador
skis|los esquís|esqui
snowboard|la tabla de snowboard|
sports ball|la pelota|balon
kite|la cometa|
baseball bat|el bate de béisbol|bate
baseball glove|el guante de béisbol|
skateboard|el monopatín|patineta
surfboard|la tabla de surf|
tennis racket|la raqueta de tenis|raqueta
bottle|la botella|
wine glass|la copa de vino|copa
cup|la taza|
fork|el tenedor|
knife|el cuchillo|
spoon|la cuchara|
bowl|el cuenco|bol
banana|el plátano|banana
apple|la manzana|
sandwich|el sándwich|bocadillo
orange|la naranja|
broccoli|el brócoli|
carrot|la zanahoria|
hot dog|el perrito caliente|
pizza|la pizza|
donut|el dónut|rosquilla,donut
cake|la tarta|pastel
chair|la silla|
couch|el sofá|sillon
potted plant|la planta|maceta
bed|la cama|
dining table|la mesa|mesa de comedor
toilet|el inodoro|vater,retrete
tv|el televisor|television,tele
laptop|el portátil|ordenador,computadora
mouse|el ratón|
remote|el mando|control remoto
keyboard|el teclado|
cell phone|el móvil|telefono,phone,cellphone,mobile phone
microwave|el microondas|
oven|el horno|
toaster|la tostadora|
sink|el fregadero|lavabo
refrigerator|la nevera|frigorifico
book|el libro|
clock|el reloj|
vase|el jarrón|florero
scissors|las tijeras|
teddy bear|el oso de peluche|peluche
hair drier|el secador|secador de pelo
toothbrush|el cepillo de dientes|cepillo dental'''


def normalize(text):
    return ''.join(c for c in unicodedata.normalize('NFD', text.lower())
                   if unicodedata.category(c) != 'Mn')


OBJECT_ES = {}
OBJECT_ALIASES = {}
for row in _ROWS.splitlines():
    canonical, name, extra = row.strip().split('|')
    OBJECT_ES[canonical] = name
    noun = name.split(' ', 1)[1]
    aliases = [canonical, noun, *filter(None, extra.split(','))]
    # Regular Spanish plurals; explicit multiword aliases stay intact.
    if ' ' not in noun and not noun.endswith('s'):
        aliases.append(noun + ('s' if normalize(noun)[-1] in 'aeiou' else 'es'))
    for alias in aliases:
        OBJECT_ALIASES[normalize(alias)] = canonical
OBJECT_ALIASES = dict(sorted(OBJECT_ALIASES.items(), key=lambda item: -len(item[0])))


def extract_object(text):
    text = normalize(text)
    for alias, canonical in OBJECT_ALIASES.items():
        if re.search(r'(?<!\w)' + re.escape(alias) + r'(?!\w)', text):
            return canonical
    return None
