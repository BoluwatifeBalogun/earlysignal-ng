"""Reference data for the Nigeria-wide case study.

The seminar report scopes the prototype to one department. This build widens
the case study to Nigerian tertiary institutions as a whole, so every student
carries an institution, an institution type and a state. States roll up into
the six geopolitical zones, and the institution type decides which GPA scale
the "previous result" indicator is read on.
"""

ZONES = {
    "North Central": ["Benue", "FCT", "Kogi", "Kwara", "Nasarawa", "Niger", "Plateau"],
    "North East": ["Adamawa", "Bauchi", "Borno", "Gombe", "Taraba", "Yobe"],
    "North West": ["Jigawa", "Kaduna", "Kano", "Katsina", "Kebbi", "Sokoto", "Zamfara"],
    "South East": ["Abia", "Anambra", "Ebonyi", "Enugu", "Imo"],
    "South South": ["Akwa Ibom", "Bayelsa", "Cross River", "Delta", "Edo", "Rivers"],
    "South West": ["Ekiti", "Lagos", "Ogun", "Ondo", "Osun", "Oyo"],
}

STATE_TO_ZONE = {state: zone for zone, states in ZONES.items() for state in states}
STATES = sorted(STATE_TO_ZONE)
STATE_CHOICES = [(s, s) for s in STATES]
ZONE_NAMES = list(ZONES)

UNIVERSITY = "University"
POLYTECHNIC = "Polytechnic"
COLLEGE = "College of Education"

INSTITUTION_TYPES = [UNIVERSITY, POLYTECHNIC, COLLEGE]
INSTITUTION_TYPE_CHOICES = [(t, t) for t in INSTITUTION_TYPES]

# Grade point scale used for the "previous result" indicator.
# Polytechnics follow the NBTE 4.00 scale; universities and colleges of
# education report on a 5.00 scale.
GPA_SCALE = {UNIVERSITY: 5.0, POLYTECHNIC: 4.0, COLLEGE: 5.0}

LEVELS = {
    UNIVERSITY: ["100 Level", "200 Level", "300 Level", "400 Level", "500 Level"],
    POLYTECHNIC: ["ND 1", "ND 2", "HND 1", "HND 2"],
    COLLEGE: ["NCE 1", "NCE 2", "NCE 3"],
}
LEVEL_CHOICES = [(lv, lv) for group in LEVELS.values() for lv in group]

SEMESTER_CHOICES = [("First", "First semester"), ("Second", "Second semester")]

# Minimum attendance most Nigerian institutions require before a student may
# sit an examination.
ATTENDANCE_REQUIREMENT = 75

# (name, type, state). Used only to give the synthetic demo data a realistic
# national spread. No real student data from these institutions is included.
INSTITUTIONS = [
    ("Yaba College of Technology", POLYTECHNIC, "Lagos"),
    ("University of Lagos", UNIVERSITY, "Lagos"),
    ("Federal College of Education (Technical), Akoka", COLLEGE, "Lagos"),
    ("University of Ibadan", UNIVERSITY, "Oyo"),
    ("The Polytechnic, Ibadan", POLYTECHNIC, "Oyo"),
    ("Obafemi Awolowo University", UNIVERSITY, "Osun"),
    ("Federal Polytechnic, Ilaro", POLYTECHNIC, "Ogun"),
    ("Federal University of Technology, Akure", UNIVERSITY, "Ondo"),
    ("Federal Polytechnic, Ado-Ekiti", POLYTECHNIC, "Ekiti"),
    ("University of Nigeria, Nsukka", UNIVERSITY, "Enugu"),
    ("Institute of Management and Technology, Enugu", POLYTECHNIC, "Enugu"),
    ("Nnamdi Azikiwe University", UNIVERSITY, "Anambra"),
    ("Federal Polytechnic, Nekede", POLYTECHNIC, "Imo"),
    ("Abia State University", UNIVERSITY, "Abia"),
    ("Ebonyi State College of Education, Ikwo", COLLEGE, "Ebonyi"),
    ("University of Benin", UNIVERSITY, "Edo"),
    ("Auchi Polytechnic", POLYTECHNIC, "Edo"),
    ("University of Port Harcourt", UNIVERSITY, "Rivers"),
    ("Niger Delta University", UNIVERSITY, "Bayelsa"),
    ("University of Calabar", UNIVERSITY, "Cross River"),
    ("Delta State Polytechnic, Ogwashi-Uku", POLYTECHNIC, "Delta"),
    ("Akwa Ibom State College of Education, Afaha Nsit", COLLEGE, "Akwa Ibom"),
    ("University of Abuja", UNIVERSITY, "FCT"),
    ("University of Ilorin", UNIVERSITY, "Kwara"),
    ("Federal Polytechnic, Offa", POLYTECHNIC, "Kwara"),
    ("Federal University of Technology, Minna", UNIVERSITY, "Niger"),
    ("Federal Polytechnic, Bida", POLYTECHNIC, "Niger"),
    ("University of Jos", UNIVERSITY, "Plateau"),
    ("Benue State University", UNIVERSITY, "Benue"),
    ("Federal Polytechnic, Nasarawa", POLYTECHNIC, "Nasarawa"),
    ("Federal College of Education, Okene", COLLEGE, "Kogi"),
    ("Ahmadu Bello University", UNIVERSITY, "Kaduna"),
    ("Kaduna Polytechnic", POLYTECHNIC, "Kaduna"),
    ("Federal College of Education, Zaria", COLLEGE, "Kaduna"),
    ("Bayero University, Kano", UNIVERSITY, "Kano"),
    ("Kano State Polytechnic", POLYTECHNIC, "Kano"),
    ("Usmanu Danfodiyo University", UNIVERSITY, "Sokoto"),
    ("Umaru Musa Yar'adua University", UNIVERSITY, "Katsina"),
    ("Waziri Umaru Federal Polytechnic, Birnin Kebbi", POLYTECHNIC, "Kebbi"),
    ("Federal University, Dutse", UNIVERSITY, "Jigawa"),
    ("Federal College of Education (Technical), Gusau", COLLEGE, "Zamfara"),
    ("University of Maiduguri", UNIVERSITY, "Borno"),
    ("Abubakar Tafawa Balewa University", UNIVERSITY, "Bauchi"),
    ("Federal Polytechnic, Bauchi", POLYTECHNIC, "Bauchi"),
    ("Modibbo Adama University, Yola", UNIVERSITY, "Adamawa"),
    ("Federal College of Education, Yola", COLLEGE, "Adamawa"),
    ("Gombe State University", UNIVERSITY, "Gombe"),
    ("Taraba State University", UNIVERSITY, "Taraba"),
    ("Federal Polytechnic, Damaturu", POLYTECHNIC, "Yobe"),
]

DEPARTMENTS = [
    "Computer Science",
    "Electrical Engineering",
    "Accountancy",
    "Business Administration",
    "Mass Communication",
    "Science Laboratory Technology",
    "Statistics",
    "Civil Engineering",
    "Economics",
    "Biology Education",
]


def zone_for(state: str) -> str:
    return STATE_TO_ZONE.get(state, "")


def scale_for(institution_type: str) -> float:
    return GPA_SCALE.get(institution_type, 5.0)


def normalise_gpa(gpa: float, institution_type: str) -> float:
    """Express a GPA as a percentage of its scale so one model serves both
    the 4.00 and the 5.00 systems."""
    return round(float(gpa) / scale_for(institution_type) * 100.0, 2)
