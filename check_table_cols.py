from astroquery.gaia import Gaia

def test():
    query = """
        SELECT TOP 5
            source_id, ra, dec, parallax, pmra, pmdec, phot_g_mean_mag, bp_rp
        FROM gaiadr3.gaia_source
    """
    job = Gaia.launch_job_async(query, verbose=False)
    table = job.get_results()
    print("Columns:", table.colnames)
    with open("cols.txt", "w") as f:
        f.write(str(table.colnames))
    for record in table:
        print(record.keys())
        break

if __name__ == "__main__":
    test()
