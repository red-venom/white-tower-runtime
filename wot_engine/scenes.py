"""Original assessment situations, with costs supplied by progression rules.

These are campaign inventions, not descriptions of canonical test visions.
They never specify the player's memories, emotions, promises or Ajah.
"""
FORMAL = {
    'accepted': (
        ('A familiar request',
         'Beyond the first arch, a person asks you to abandon your own work and take responsibility for theirs. '
         'You decide who, if anyone, this vision resembles. The way onward remains visible.',
         'State the help you can realistically give, then leave a clear explanation.',
         'Offer a defined day of service after the test, then continue.'),
        ('Two calls for help',
         'The second arch shows two groups waiting for the same small store of supplies. '
         'Both have reasonable needs. The vision asks what you will undertake yourself and what you will entrust to others.',
         'Explain the limits of your role and document a handover.',
         'Undertake one later service day without promising to do everything.'),
        ('A future left open',
         'The third arch presents a quiet life that you may describe, accept as an imagined possibility, or leave unspecified. '
         'A request for help remains beside the way onward. No future, feeling or loyalty is assigned to you.',
         'Give a clear account of your present decision without making a new promise.',
         'Make one bounded service commitment while leaving your future choices open.'),
    ),
    'shawl': (
        ('Keeping the first sequence',
         'The assessment begins with ordered forms F001–F025. An examiner requests help while the prepared work must continue. '
         'Your rehearsed technique is assured; the choice concerns the responsibility you take on.',
         'State your limits and prepare a later explanation.',
         'Offer one later day of useful service.'),
        ('Conflicting instructions',
         'Forms F026–F050 continue while two requests compete for your attention. '
         'Neither examiner can choose your priorities for you. You may describe how you make the handover clear.',
         'Document which responsibility you can accept and which needs another person.',
         'Keep the assessment sequence and offer a bounded later service day.'),
        ('An incomplete account',
         'During forms F051–F075, a request arrives with missing details. '
         'The assessment does not require you to pretend certainty or invent a fact.',
         'Explain what remains uncertain and record the questions for later.',
         'Undertake a later service day to help establish the missing facts.'),
        ('The final handover',
         'Forms F076–F100 bring the ordered sequence to its end. A final request asks what you will do after the assessment. '
         'Completion preserves the qualification you earned; rank, Oaths and Ajah remain your later explicit choices.',
         'State a clear boundary and complete the written handover afterward.',
         'Offer one defined service day after completion.'),
    ),
}


def assessment(state):
    for kind in ('accepted','shawl'):
        test=state['progression'][kind+'_test']
        if test['started'] and not test['completed']:
            title, situation, explain, service = FORMAL[kind][test['scene']]
            return {'id':f"{kind}-scene-{test['scene']+1}", 'title':title,
                    'description':situation+' Both responses complete the scene. Explaining limits adds ten minutes of follow-up work after the test; offering service adds one later service day.',
                    'lore_class':'invention', 'choices':[
                        {'label':explain, 'intent':{'verb':'formal_scene','kind':kind,'choice':'explain_limits'}},
                        {'label':service, 'intent':{'verb':'formal_scene','kind':kind,'choice':'offer_service'}}]}
    return None


def regional_scene(state):
    from .regional import ASSIGNMENTS, CHAPTER_AIMS
    chapter=state['progression']['chapter']
    number=chapter['number']
    aim=CHAPTER_AIMS[number-1] if number<=12 else 'Undertake a new service after the shawl.'
    assignment=state['world']['region']['assignment']
    details=ASSIGNMENTS.get(number,('Choose how to hand over the new service result.',))[0]
    if chapter['stage']=='boundary':
        text='This chapter is complete. Its earned progress is saved. You may spend banked points and review your next commitments before beginning another chapter.'
    elif assignment['status']=='resolved':
        text='The chapter assignment is resolved. Its result remains part of the record. '+aim+' Your training review shows the remaining requirements.'
    else:
        text=details+' '+aim
    return {'id':f'region-chapter-{number}', 'description':text}
