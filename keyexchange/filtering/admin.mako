<html>
 <body>
   <h1>Blacklisted IPs</h1>
   %if not ips:
   None
   %endif
   %if ips:
   <form action="${admin_page}" method="POST">
    <table border="1">
     <tr>
       <th>IP</th>
       <th>Remove from blacklist</th>
     </tr>
     %for ip in ips:
     <tr>
      <td>${ip}</td> 
      <td><input type="checkbox" name="${ip}"></input></td>
     </tr>
     %endfor
    </table>
    <input type="submit"></input>
   </form>
   %endif
 </body>
</html>
