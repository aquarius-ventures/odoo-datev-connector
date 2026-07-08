"""Migrate the old datev_sandbox_mode boolean to the datev_mode selection.

Mapping:
- sandbox_mode True  -> 'sandbox'
- sandbox_mode False + credentials configured -> 'production'
  (that was the previous meaning of an unchecked box)
- otherwise -> 'off' (new safe default)
"""


def migrate(cr, version):
    cr.execute(
        """
        UPDATE res_company
           SET datev_mode = CASE
               WHEN datev_sandbox_mode IS TRUE THEN 'sandbox'
               WHEN COALESCE(datev_client_id, '') != '' THEN 'production'
               ELSE 'off'
           END
         WHERE datev_mode IS NULL
        """
    )
