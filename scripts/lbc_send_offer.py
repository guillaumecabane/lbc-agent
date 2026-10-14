"""Send an exact message and formal seller offer in a Leboncoin conversation, then verify both.
Usage: lbc_send_offer.py <conversation_id> <expected_title> <message_file> <price_eur>
"""
import re,sys
from playwright.sync_api import sync_playwright
from lbc_config import CDP
CID,TITLE,MSGF,PRICE=sys.argv[1:5]; MSG=open(MSGF).read().strip()
with sync_playwright() as p:
 b=p.chromium.connect_over_cdp(CDP);pg=b.contexts[0].new_page()
 try:
  pg.goto(f'https://www.leboncoin.fr/messages/id/{CID}',wait_until='domcontentloaded',timeout=90000);pg.wait_for_timeout(6000)
  page_text=pg.inner_text('body')
  if TITLE not in page_text: raise RuntimeError('expected title not found')
  if MSG not in page_text:
   ta=pg.locator('textarea').first; ta.click();ta.fill(MSG)
   if ta.input_value()!=MSG: raise AssertionError('message input mismatch')
   send=pg.get_by_role('button',name='Envoyer mon message',exact=True)
   if send.count()!=1 or not send.is_enabled(): raise RuntimeError('send button unavailable')
   send.click();pg.wait_for_timeout(4000)
   if MSG not in pg.inner_text('body'): raise AssertionError('sent message not visible')

  make=pg.get_by_role('button',name='Faire une offre',exact=True)
  if not make.count():
   refuse=pg.get_by_role('button',name=re.compile(r"Refuser l'offre",re.I))
   if not refuse.count() or not refuse.first.is_enabled(): raise RuntimeError('Neither counter-offer nor refusal is available')
   refuse.first.click();pg.wait_for_timeout(1000)
   dialogs=pg.get_by_role('dialog')
   if dialogs.count():
    dlg=dialogs.last
    confirm=dlg.get_by_role('button',name=re.compile(r"Refuser",re.I))
    if confirm.count(): confirm.last.click()
   pg.wait_for_timeout(4000)
   make=pg.get_by_role('button',name='Faire une offre',exact=True)
  if make.count()!=1 or not make.is_enabled(): raise RuntimeError('Faire une offre unavailable after refusing incoming offer')
  make.click();pg.wait_for_timeout(1500)
  dlg=pg.get_by_role('dialog').last
  if not dlg.count() or 'Proposer un nouveau prix' not in dlg.inner_text(): raise RuntimeError('offer dialog unavailable')
  other=dlg.get_by_text(re.compile(r'Autre prix',re.I))
  if other.count(): other.first.click();pg.wait_for_timeout(500)
  inp=dlg.locator('input#price')
  if not inp.count(): inp=dlg.locator('input').filter(has_not=dlg.locator('[type=hidden]')).last
  inp.click(); inp.press('Control+A'); inp.press_sequentially(PRICE,delay=100); pg.wait_for_timeout(700)
  if inp.input_value()!=PRICE: raise AssertionError('offer price mismatch')
  propose=dlg.get_by_role('button',name=re.compile(r'^Proposer'))
  if propose.count()!=1 or not propose.is_enabled(): raise RuntimeError('Proposer unavailable')
  propose.click();pg.wait_for_timeout(5000)
  final=pg.inner_text('body')
  ok='Offre envoyée' in final and PRICE in final
  print(f'message_visible={MSG in final} offer_confirmed={ok} price={PRICE}')
  if not ok: raise AssertionError('formal offer confirmation missing')
 finally: pg.close()
