"""Jetons : édition `t*` rattachée à l'extension « Extras » / « Tokens » de Cardmarket, puis idProduct retrouvé par le nom."""
from magicscanner.catalog import cardmarket

WAR, XMH2 = 2439, 4244


def _set(con, code, name, parent, set_type="token"):
    con.execute("INSERT INTO sets (code, name, set_type, parent_set_code) VALUES (?,?,?,?)", (code, name, set_type, parent))


def _expansion(con, id_expansion, name, sample_code):
    con.execute("INSERT INTO cm_expansions VALUES (?,?,?,?)", (id_expansion, name.replace(": ", "-").replace(" ", "-"), name, sample_code))


def _product(con, id_product, name, expansion):
    con.execute("INSERT INTO cm_products VALUES (?,?,?,NULL)", (id_product, name, expansion))


def _card(con, card_id, name, number, set_code="tmh2", product=None, type_line="Token Creature"):
    con.execute("INSERT INTO cards (id, oracle_id, name, front_name, set_code, collector_number, rarity, cardmarket_id, type_line) "
                "VALUES (?,?,?,?,?,?,?,?,?)", (card_id, "o-" + card_id, name, name, set_code, number, "common", product, type_line))


def _linked(con, card_id):
    return con.execute("SELECT cardmarket_id FROM cards WHERE id=?", (card_id,)).fetchone()[0]


def _expansion_of(con, code):
    return con.execute("SELECT cm_id_expansion FROM sets WHERE code=?", (code,)).fetchone()[0]


def _mh2(con):
    _set(con, "tmh2", "Modern Horizons 2 Tokens", "mh2")
    _expansion(con, WAR, "War of the Spark", "WAR")
    _expansion(con, XMH2, "Modern Horizons 2: Extras", "XMH2")
    _product(con, 1, "Counterspell", XMH2)                      # une carte « extra » : pas un jeton
    _product(con, 568774, "Beast Token (Green 4/4)", XMH2)


def test_edition_de_jetons_rattachee_a_ses_extras_malgre_les_votes_de_scryfall(con):
    """Scryfall donne à des jetons de tmh2 des produits de War of the Spark : le vote majoritaire se trompait."""
    _mh2(con)
    _product(con, 900, "Zombie Token", WAR)
    _card(con, "z", "Zombie", "6", product=900)
    cardmarket.map_sets(con)
    assert _expansion_of(con, "tmh2") == XMH2
    assert con.execute("SELECT cm_slug FROM sets WHERE code='tmh2'").fetchone()[0] == "Modern-Horizons-2-Extras"


def test_extension_tokens_preferee_quand_elle_contient_les_jetons(con):
    _set(con, "tlci", "Lost Caverns Tokens", "lci")
    _expansion(con, 5491, "The Lost Caverns of Ixalan: Extras", "XLCI")
    _expansion(con, 5536, "The Lost Caverns of Ixalan: Tokens", "TLCI")
    _product(con, 1, "Treasure Token", 5536)
    cardmarket.map_sets(con)
    assert _expansion_of(con, "tlci") == 5536


def test_edition_de_jetons_sans_extension_dediee_garde_le_vote(con):
    _set(con, "thou", "Hour of Devastation Tokens", "hou")
    _expansion(con, 1731, "Hour of Devastation", "HOU")
    _product(con, 5, "Zombie Token", 1731)
    _card(con, "z", "Zombie", "1", set_code="thou", product=5)
    cardmarket.map_sets(con)
    assert _expansion_of(con, "thou") == 1731


def test_jeton_unique_rattache_par_son_nom(con):
    _mh2(con)
    _card(con, "b", "Beast", "9")
    cardmarket.map_sets(con)
    assert cardmarket.link_list_cards(con) == 1
    assert _linked(con, "b") == 568774


def test_carte_extra_homonyme_n_est_pas_un_jeton(con):
    _mh2(con)
    _product(con, 2, "Spider", XMH2)                            # pas « Token » : ne doit pas servir de produit
    _card(con, "s", "Spider", "7")
    cardmarket.map_sets(con)
    assert cardmarket.link_list_cards(con) == 0


def test_jetons_homonymes_restent_sans_identifiant(con):
    """Deux « Clue » : l'ordre des idProduct ne suit pas toujours les numéros, on ne devine pas."""
    _mh2(con)
    _product(con, 568779, "Clue Token", XMH2)
    _product(con, 568780, "Clue Token", XMH2)
    _card(con, "c14", "Clue", "14")
    _card(con, "c15", "Clue", "15")
    cardmarket.map_sets(con)
    assert cardmarket.link_list_cards(con) == 0
    assert _linked(con, "c14") is None and _linked(con, "c15") is None


def test_jeton_dont_un_homonyme_a_un_produit_etranger_n_est_pas_devine(con):
    _mh2(con)
    _product(con, 568779, "Clue Token", XMH2)
    _product(con, 900, "Clue Token", WAR)
    _card(con, "c14", "Clue", "14", product=900)                # identifiant Scryfall d'une autre extension
    _card(con, "c15", "Clue", "15")
    cardmarket.map_sets(con)
    assert cardmarket.link_list_cards(con) == 0


def test_jeton_double_face_retrouve_face_par_face(con):
    """Cardmarket : « Bird Token (W 1/1) // Clue Token » ; Scryfall : « Bird // Clue »."""
    _mh2(con)
    _product(con, 569497, "Bird Token (W 1/1) // Clue Token", XMH2)
    _card(con, "bc", "Bird // Clue", "30", type_line="Token Creature — Bird // Token Artifact — Clue")
    cardmarket.map_sets(con)
    assert cardmarket.link_list_cards(con) == 1
    assert _linked(con, "bc") == 569497


def test_jeton_ne_prend_pas_un_double_face_quand_il_y_en_a_plusieurs(con):
    _mh2(con)
    _product(con, 569497, "Bird Token (W 1/1) // Clue Token", XMH2)
    _product(con, 569498, "Beast Token (G 4/4) // Clue Token", XMH2)   # deux produits au dos : on ne choisit pas
    _card(con, "c", "Clue", "14")
    cardmarket.map_sets(con)
    assert cardmarket.link_list_cards(con) == 0


def test_emblème_rattaché_par_son_nom_complet(con):
    """Un emblème n'a pas de suffixe « Token » chez Cardmarket ; le jeton-créature homonyme d'une carte « extra » reste refusé."""
    _mh2(con)
    _product(con, 77, "Kaito Shizuki Emblem", XMH2)
    _card(con, "e", "Kaito Shizuki Emblem", "1", type_line="Emblem")
    cardmarket.map_sets(con)
    assert cardmarket.link_list_cards(con) == 1
    assert _linked(con, "e") == 77


def test_edition_mixte_ne_rattache_pas_un_nom_present_dans_l_extension_soeur(con):
    """tdmu : des cartes vont dans « Extras » et d'autres dans « Commander: … Extras » ; un « Treasure » vendu dans les deux est ambigu."""
    _set(con, "tdmu", "Dominaria United Tokens", "dmu")
    _expansion(con, 5073, "Dominaria United: Extras", "XDMU")
    _expansion(con, 5123, "Commander: Dominaria United: Extras", "XDMC")
    _product(con, 1, "Treasure Token", 5073)
    _product(con, 2, "Treasure Token", 5123)
    _product(con, 3, "Cat Token (W 1/1)", 5073)
    _product(con, 4, "Soldier Token (W 1/1)", 5073)
    _product(con, 5, "Elf Token (G 1/1)", 5123)
    _card(con, "s", "Soldier", "5", set_code="tdmu", product=4)
    _card(con, "elf", "Elf", "6", set_code="tdmu", product=5)          # Scryfall l'envoie dans l'extension sœur
    _card(con, "t", "Treasure", "20", set_code="tdmu")
    _card(con, "cat", "Cat", "3", set_code="tdmu")
    cardmarket.map_sets(con)
    assert _expansion_of(con, "tdmu") == 5073
    assert cardmarket.link_list_cards(con) == 1
    assert _linked(con, "t") is None and _linked(con, "cat") == 3


def test_double_nom_retrouve_a_l_envers(con):
    """Scryfall : « Undercity // The Initiative » ; Cardmarket : « The Initiative // Undercity »."""
    _mh2(con)
    _product(con, 662252, "The Initiative // Undercity", XMH2)
    _card(con, "u", "Undercity // The Initiative", "20", type_line="Dungeon // Dungeon")
    cardmarket.map_sets(con)
    assert cardmarket.link_list_cards(con) == 1
    assert _linked(con, "u") == 662252


def test_rattachement_reexecutable(con):
    _mh2(con)
    _card(con, "b", "Beast", "9")
    cardmarket.map_sets(con)
    cardmarket.link_list_cards(con)
    cardmarket.map_sets(con)
    assert cardmarket.link_list_cards(con) == 0
    assert _linked(con, "b") == 568774 and _expansion_of(con, "tmh2") == XMH2


# --- homonymes : l'idProduct suit le numéro de collection dans l'extension (ancre = carte déjà liée) ---

def _clues(con, below=568778, above=568781, names=("Clue Token", "Clue Token")):
    """tmh2 : Beast n°13 et Elf n°16 déjà liés ; deux Clue (n°14 et 15) sans identifiant."""
    _mh2(con)
    _product(con, below, "Beast Token (Green 4/4)", XMH2)
    _product(con, above, "Elf Token (Green 1/1)", XMH2)
    _product(con, 568779, names[0], XMH2)
    _product(con, 568780, names[1], XMH2)
    _card(con, "beast", "Beast", "13", product=below)
    _card(con, "elf", "Elf", "16", product=above)
    _card(con, "c14", "Clue", "14")
    _card(con, "c15", "Clue", "15")
    cardmarket.map_sets(con)


def test_homonymes_rattaches_par_le_decalage_des_ancres(con):
    _clues(con)
    assert cardmarket.link_list_cards(con) == 2
    assert _linked(con, "c14") == 568779 and _linked(con, "c15") == 568780


def test_homonymes_decalage_incoherent_entre_les_deux_ancres_pas_de_lien(con):
    _clues(con, above=568782)                                   # l'ancre de droite ne suit plus le même décalage
    assert cardmarket.link_list_cards(con) == 0
    assert _linked(con, "c14") is None and _linked(con, "c15") is None


def test_homonymes_le_produit_vise_doit_porter_le_nom_de_la_carte(con):
    _clues(con, names=("Food Token", "Clue Token"))
    assert cardmarket.link_list_cards(con) == 1
    assert _linked(con, "c14") is None and _linked(con, "c15") == 568780


def test_homonymes_sans_ancre_dans_l_extension_pas_de_lien(con):
    """Une ancre dont le produit est d'une autre extension (identifiant Scryfall étranger) ne sert pas."""
    _mh2(con)
    _product(con, 568779, "Clue Token", XMH2)
    _product(con, 568780, "Clue Token", XMH2)
    _product(con, 568778, "Beast Token", WAR)
    _card(con, "beast", "Beast", "13", product=568778)
    _card(con, "c14", "Clue", "14")
    _card(con, "c15", "Clue", "15")
    cardmarket.map_sets(con)
    assert cardmarket.link_list_cards(con) == 0


def test_jeton_dont_l_identifiant_scryfall_est_etranger_retrouve_sa_place_par_les_ancres(con):
    """tmh2 n°6 : Scryfall donne un produit de War of the Spark, mais le produit à sa position porte son nom."""
    _mh2(con)
    _product(con, 568770, "Elf Token", XMH2)
    _product(con, 568771, "Zombie Token", XMH2)
    _product(con, 568772, "Zombie Army Token", XMH2)
    _product(con, 900, "Zombie Token", WAR)
    _card(con, "e5", "Elf", "5", product=568770)
    _card(con, "e9", "Elf", "9", product=568774)
    _card(con, "z6", "Zombie", "6", product=900)
    cardmarket.map_sets(con)
    assert cardmarket.link_list_cards(con) == 1
    assert _linked(con, "z6") == 568771


def test_donjon_n_est_pas_rattache_par_les_ancres(con):
    """tafr : les donjons existent aussi en version oversized chez Cardmarket ; on ne devine pas leur produit par la position."""
    _set(con, "tafr", "Adventures in the Forgotten Realms Tokens", "afr")
    _expansion(con, 4260, "Adventures in the Forgotten Realms: Extras", "XAFR")
    _product(con, 577354, "Dungeon of the Mad Mage", 4260)
    _product(con, 577355, "Lost Mine of Phandelver", 4260)
    _product(con, 685440, "Lost Mine of Phandelver", 4260)
    _product(con, 577356, "Tomb of Annihilation", 4260)
    _card(con, "d20", "Dungeon of the Mad Mage", "20", set_code="tafr", product=577354, type_line="Dungeon")
    _card(con, "d22", "Tomb of Annihilation", "22", set_code="tafr", product=577356, type_line="Dungeon")
    _card(con, "d21", "Lost Mine of Phandelver", "21", set_code="tafr", type_line="Dungeon")
    cardmarket.map_sets(con)
    assert cardmarket.link_list_cards(con) == 0
    assert _linked(con, "d21") is None


# --- jeton imprimé seulement au dos d'une autre carte ---

def _afr(con):
    _set(con, "tafr", "Adventures in the Forgotten Realms Tokens", "afr")
    _expansion(con, 4260, "Adventures in the Forgotten Realms: Extras", "XAFR")
    _product(con, 570638, "Goblin Token (R 1/1) // Dungeon of the Mad Mage", 4260)
    _product(con, 570640, "Skeleton Token (B 1/1) // Lost Mine of Phandelver", 4260)


def test_jeton_sans_produit_simple_rattache_au_produit_double_face_unique(con):
    _afr(con)
    _card(con, "g", "Goblin", "12", set_code="tafr")
    _card(con, "s", "Skeleton", "6", set_code="tafr")
    cardmarket.map_sets(con)
    assert cardmarket.link_list_cards(con) == 2
    assert _linked(con, "g") == 570638 and _linked(con, "s") == 570640


def test_jeton_au_dos_de_plusieurs_produits_double_face_pas_de_lien(con):
    _afr(con)
    _product(con, 570700, "Goblin Token (R 1/1) // Tomb of Annihilation", 4260)
    _card(con, "g", "Goblin", "12", set_code="tafr")
    cardmarket.map_sets(con)
    assert cardmarket.link_list_cards(con) == 0


def test_produit_double_face_deja_pris_n_est_pas_reutilise(con):
    _afr(con)
    _card(con, "bc", "Goblin // Dungeon of the Mad Mage", "40", set_code="tafr", product=570638)
    _card(con, "g", "Goblin", "12", set_code="tafr")
    cardmarket.map_sets(con)
    assert cardmarket.link_list_cards(con) == 0


def test_jeton_avec_produit_simple_ne_prend_pas_le_double_face(con):
    """Un produit simple de ce nom existe (même pris ou ambigu) : le double face n'est pas un repli."""
    _afr(con)
    _product(con, 1, "Goblin Token (R 1/1)", 4260)
    _product(con, 2, "Goblin Token (R 2/2)", 4260)
    _card(con, "g", "Goblin", "12", set_code="tafr")
    cardmarket.map_sets(con)
    assert cardmarket.link_list_cards(con) == 0


def test_carte_non_jeton_n_est_pas_rattachee_a_un_produit_double_face(con):
    _afr(con)
    _card(con, "d", "Dungeon of the Mad Mage", "20", set_code="tafr", type_line="Dungeon")
    cardmarket.map_sets(con)
    assert cardmarket.link_list_cards(con) == 0


# --- relecture : une seule ancre, homonymes, extension sœur, idempotence ---

def test_une_seule_ancre_suffit(con):
    """Treasure n°20 : seule l'ancre de gauche existe, le décalage n'a pas de confirmation de l'autre côté."""
    _mh2(con)
    _product(con, 568784, "Beast Token (G 4/4)", XMH2)
    _product(con, 568785, "Treasure Token", XMH2)
    _card(con, "b19", "Beast", "19", product=568784)
    _card(con, "t20", "Treasure", "20")
    cardmarket.map_sets(con)
    assert cardmarket.link_list_cards(con) == 1
    assert _linked(con, "t20") == 568785


def test_double_face_pas_de_lien_si_deux_jetons_homonymes(con):
    """Deux « Goblin » sans id pour un seul produit double face : on ne sait pas lequel il porte."""
    _afr(con)
    _card(con, "g1", "Goblin", "12", set_code="tafr")
    _card(con, "g2", "Goblin", "13", set_code="tafr")
    cardmarket.map_sets(con)
    assert cardmarket.link_list_cards(con) == 0


def test_jeton_etranger_dont_le_nom_est_dans_l_extension_soeur_n_est_pas_reecrit(con):
    """tdmu : n°6 a un id étranger ; « Elf » se vend aussi dans l'extension sœur, la position ne tranche pas."""
    _set(con, "tdmu", "Dominaria United Tokens", "dmu")
    _expansion(con, 5073, "Dominaria United: Extras", "XDMU")
    _expansion(con, 5123, "Commander: Dominaria United: Extras", "XDMC")
    _product(con, 105, "Soldier Token (W 1/1)", 5073)
    _product(con, 106, "Elf Token (G 1/1)", 5073)
    _product(con, 107, "Cat Token (W 1/1)", 5073)
    _product(con, 900, "Elf Token (G 1/1)", 5123)
    _card(con, "s5", "Soldier", "5", set_code="tdmu", product=105)
    _card(con, "elf", "Elf", "6", set_code="tdmu", product=900)       # extension sœur
    _card(con, "c7", "Cat", "7", set_code="tdmu", product=107)
    cardmarket.map_sets(con)
    assert cardmarket.link_list_cards(con) == 0
    assert _linked(con, "elf") == 900


def test_nouvelles_regles_reexecutables(con):
    _clues(con)
    _afr(con)
    _card(con, "g", "Goblin", "12", set_code="tafr")
    cardmarket.map_sets(con)
    assert cardmarket.link_list_cards(con) == 3
    assert cardmarket.link_list_cards(con) == 0
    assert _linked(con, "c14") == 568779 and _linked(con, "g") == 570638
